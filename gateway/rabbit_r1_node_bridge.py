"""
Rabbit R1 <-> Hermes bridge over the OpenClaw WebSocket node protocol.

L1 scope:

- accept `node.event` with `voice.transcript`
- expose a thin callback API keyed only by `nodeId`
- keep OpenClaw auth/pairing/device details private inside the bridge
- send Hermes replies back over the node event channel using
  `node.invoke.request` envelopes

The outbound command names are bridge-private for now and may be renamed once
the R1-side Hermes shim is finalized.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

try:
    from aiohttp import web
except Exception:  # pragma: no cover - optional runtime dependency
    web = None  # type: ignore[assignment]

from gateway.openclaw_protocol import (
    ConnectParams,
    ConnectRequestFrame,
    HelloOk,
    HelloOkAuth,
    HelloOkFeatures,
    HelloOkPolicy,
    HelloOkResponseFrame,
    HelloOkServer,
    NodeEventParams,
    RequestFrame,
    Snapshot,
    StateVersion,
    VoiceTranscriptPayload,
    build_device_auth_payload,
    build_device_auth_payload_v3,
    verify_device_signature,
)

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[..., Any]
DisconnectCallback = Callable[[str], Any]
PairingRequiredCallback = Callable[[str, str], Any]

ERROR_DEVICE_PAIRING_REQUIRED = "DEVICE_PAIRING_REQUIRED"
ERROR_NODE_PAIRING_REQUIRED = "NODE_PAIRING_REQUIRED"
ERROR_NODE_INVOKE_UNSUPPORTED = "NODE_INVOKE_UNSUPPORTED"
ERROR_CANVAS_UNSUPPORTED = "CANVAS_UNSUPPORTED"
ERROR_EXEC_APPROVAL_UNSUPPORTED = "EXEC_APPROVAL_UNSUPPORTED"
ERROR_PROTOCOL_UNSUPPORTED = "PROTOCOL_UNSUPPORTED"
ERROR_AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
ERROR_DEVICE_SIGNATURE_INVALID = "DEVICE_SIGNATURE_INVALID"


@dataclass
class RabbitR1BridgeConfig:
    host: str = "0.0.0.0"
    port: int = 18789
    auth_token: Optional[str] = None
    protocol_version: int = 3
    auto_approve_pairing: bool = False
    default_session_key: str = "agent:main:main"
    state_dir: Optional[Path] = None


@dataclass
class RabbitR1NodeContext:
    node_id: str
    client_id: str
    client_mode: str
    display_name: Optional[str] = None
    platform: Optional[str] = None
    version: Optional[str] = None
    device_family: Optional[str] = None
    model_identifier: Optional[str] = None
    device_id: Optional[str] = None
    public_key: Optional[str] = None
    session_key: str = "agent:main:main"
    remote_ip: Optional[str] = None
    caps: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    permissions: dict[str, bool] = field(default_factory=dict)
    connected_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class _PendingPairing:
    request_id: str
    node_id: str
    kind: str
    created_at_ms: int


@dataclass
class _ConnectionState:
    ws: Any
    context: RabbitR1NodeContext
    request_id_seq: int = 0


class RabbitR1NodeBridge:
    def __init__(self, config: RabbitR1BridgeConfig):
        self.config = config
        self._runner: Any = None
        self._site: Any = None
        self._app: Any = None
        self._connections_by_node_id: dict[str, _ConnectionState] = {}
        self._device_pairs_by_node_id: dict[str, str] = {}
        self._node_pairs_by_node_id: dict[str, str] = {}
        self._pending_pairs_by_request_id: dict[str, _PendingPairing] = {}
        self._transcript_callbacks: list[TranscriptCallback] = []
        self._disconnect_callbacks: list[DisconnectCallback] = []
        self._pairing_required_callbacks: list[PairingRequiredCallback] = []

    def on_transcript(self, callback: TranscriptCallback) -> TranscriptCallback:
        self._transcript_callbacks.append(callback)
        return callback

    def on_disconnect(self, callback: DisconnectCallback) -> DisconnectCallback:
        self._disconnect_callbacks.append(callback)
        return callback

    def on_pairing_required(self, callback: PairingRequiredCallback) -> PairingRequiredCallback:
        self._pairing_required_callbacks.append(callback)
        return callback

    async def start(self) -> None:
        if web is None:
            raise RuntimeError("Rabbit R1 bridge requires aiohttp; install hermes-agent[messaging]")
        if self._runner is not None:
            return
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_ws)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.config.host, port=self.config.port)
        await self._site.start()

    async def stop(self) -> None:
        connections = list(self._connections_by_node_id.values())
        self._connections_by_node_id.clear()
        for state in connections:
            with contextlib.suppress(Exception):
                await state.ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._app = None

    async def send_text(self, node_id: str, text: str) -> None:
        await self._send_node_command(node_id, "rabbit_r1.send_text", {"text": text})

    async def send_audio(self, node_id: str, audio_path: str, mime_type: str = "audio/mpeg") -> None:
        await self._send_node_command(
            node_id,
            "rabbit_r1.send_audio",
            {
                "audioPath": audio_path,
                "mimeType": mime_type,
            },
        )

    async def send_typing(self, node_id: str) -> None:
        if node_id not in self._connections_by_node_id:
            raise KeyError(f"unknown nodeId: {node_id}")
        return

    async def _send_node_command(self, node_id: str, command: str, params: dict[str, Any]) -> None:
        state = self._connections_by_node_id.get(node_id)
        if state is None:
            raise KeyError(f"unknown nodeId: {node_id}")
        payload = {
            "id": str(uuid4()),
            "nodeId": node_id,
            "command": command,
            "paramsJSON": json.dumps(params, ensure_ascii=False),
            "idempotencyKey": str(uuid4()),
        }
        await state.ws.send_json(
            {
                "type": "event",
                "event": "node.invoke.request",
                "payload": payload,
            }
        )

    async def _handle_ws(self, request: Any) -> Any:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        challenge = self._build_connect_challenge()
        await ws.send_json(challenge)
        node_id: Optional[str] = None
        try:
            connect_frame = await self._await_connect(ws)
            connect = connect_frame.params
            self._validate_connect(connect)
            node_id = self._resolve_node_id(connect)
            pair_error = await self._ensure_pairing(node_id, connect)
            if pair_error is not None:
                await ws.send_json(self._error_response(connect_frame.id, **pair_error))
                return ws

            context = self._build_node_context(request, node_id, connect)
            self._connections_by_node_id[node_id] = _ConnectionState(ws=ws, context=context)
            await ws.send_json(self._hello_ok_response(connect_frame.id, context))
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    continue
                await self._handle_message(node_id, message.data)
        finally:
            if node_id is not None:
                self._connections_by_node_id.pop(node_id, None)
                await self._emit_callbacks(self._disconnect_callbacks, node_id)
        return ws

    async def _await_connect(self, ws: Any) -> ConnectRequestFrame:
        async for message in ws:
            if message.type != web.WSMsgType.TEXT:
                continue
            raw = json.loads(message.data)
            frame = ConnectRequestFrame.model_validate(raw)
            return frame
        raise RuntimeError("connection closed before connect")

    def _validate_connect(self, connect: ConnectParams) -> None:
        if not (connect.minProtocol <= self.config.protocol_version <= connect.maxProtocol):
            raise ValueError(ERROR_PROTOCOL_UNSUPPORTED)
        presented_token = self._resolve_presented_token(connect)
        if self.config.auth_token and presented_token != self.config.auth_token:
            raise ValueError(ERROR_AUTH_TOKEN_INVALID)
        if connect.device is None:
            return
        if not self._verify_device_signature(connect, presented_token):
            raise ValueError(ERROR_DEVICE_SIGNATURE_INVALID)

    async def _ensure_pairing(
        self,
        node_id: str,
        connect: ConnectParams,
    ) -> Optional[dict[str, Any]]:
        if node_id not in self._device_pairs_by_node_id:
            request_id = self._create_pending_pair(node_id, "device")
            if self.config.auto_approve_pairing:
                self._device_pairs_by_node_id[node_id] = request_id
            else:
                await self._emit_callbacks(self._pairing_required_callbacks, node_id, request_id)
                return {
                    "code": ERROR_DEVICE_PAIRING_REQUIRED,
                    "message": "device pairing required",
                    "details": {"requestId": request_id, "kind": "device"},
                }
        if connect.role == "node" and node_id not in self._node_pairs_by_node_id:
            request_id = self._create_pending_pair(node_id, "node")
            if self.config.auto_approve_pairing:
                self._node_pairs_by_node_id[node_id] = request_id
            else:
                await self._emit_callbacks(self._pairing_required_callbacks, node_id, request_id)
                return {
                    "code": ERROR_NODE_PAIRING_REQUIRED,
                    "message": "node pairing required",
                    "details": {"requestId": request_id, "kind": "node"},
                }
        return None

    async def _handle_message(self, node_id: str, raw_text: str) -> None:
        frame = RequestFrame.model_validate(json.loads(raw_text))
        if frame.method != "node.event":
            state = self._connections_by_node_id.get(node_id)
            if state is not None:
                await state.ws.send_json(
                    self._error_response(
                        frame.id,
                        code=ERROR_NODE_INVOKE_UNSUPPORTED,
                        message=f"unsupported method: {frame.method}",
                    )
                )
            return
        params = NodeEventParams.model_validate(frame.params or {})
        state = self._connections_by_node_id[node_id]
        if params.event == "voice.transcript":
            payload_obj = params.payload
            if payload_obj is None and params.payloadJSON:
                payload_obj = json.loads(params.payloadJSON)
            payload = VoiceTranscriptPayload.model_validate(payload_obj or {})
            state.context.session_key = payload.sessionKey or state.context.session_key
            await self._emit_callbacks(
                self._transcript_callbacks,
                state.context,
                payload.text,
                is_voice=True,
                request_id=payload.eventId or frame.id,
                session_key=payload.sessionKey,
            )
            await state.ws.send_json({"type": "res", "id": frame.id, "ok": True, "payload": {"accepted": True}})
            return

        code = ERROR_NODE_INVOKE_UNSUPPORTED
        if params.event.startswith("canvas."):
            code = ERROR_CANVAS_UNSUPPORTED
        elif params.event.startswith("exec."):
            code = ERROR_EXEC_APPROVAL_UNSUPPORTED
        await state.ws.send_json(
            self._error_response(
                frame.id,
                code=code,
                message=f"unsupported node event: {params.event}",
            )
        )

    def _build_connect_challenge(self) -> dict[str, Any]:
        return {
            "type": "event",
            "event": "connect.challenge",
            "payload": {
                "nonce": secrets.token_urlsafe(18),
                "ts": int(time.time() * 1000),
            },
        }

    def _build_node_context(
        self,
        request: Any,
        node_id: str,
        connect: ConnectParams,
    ) -> RabbitR1NodeContext:
        return RabbitR1NodeContext(
            node_id=node_id,
            client_id=connect.client.id,
            client_mode=connect.client.mode,
            display_name=connect.client.displayName,
            platform=connect.client.platform,
            version=connect.client.version,
            device_family=connect.client.deviceFamily,
            model_identifier=connect.client.modelIdentifier,
            device_id=connect.device.id if connect.device else None,
            public_key=connect.device.publicKey if connect.device else None,
            session_key=self.config.default_session_key,
            remote_ip=request.remote,
            caps=list(connect.caps or []),
            commands=list(connect.commands or []),
            permissions=dict(connect.permissions or {}),
        )

    def _hello_ok_response(self, request_id: str, context: RabbitR1NodeContext) -> dict[str, Any]:
        payload = HelloOk(
            type="hello-ok",
            protocol=self.config.protocol_version,
            server=HelloOkServer(version="hermes-r1-bridge", connId=str(uuid4())),
            features=HelloOkFeatures(
                methods=["connect", "node.event"],
                events=["connect.challenge", "node.invoke.request"],
            ),
            snapshot=Snapshot(
                presence=[],
                health={"bridge": "ok"},
                stateVersion=StateVersion(presence=0, health=0),
                uptimeMs=0,
            ),
            auth=HelloOkAuth(deviceToken=None, role="node", scopes=[]),
            policy=HelloOkPolicy(maxPayload=26_214_400, maxBufferedBytes=52_428_800, tickIntervalMs=15_000),
        )
        return HelloOkResponseFrame(type="res", id=request_id, ok=True, payload=payload).model_dump(
            exclude_none=True
        )

    def _resolve_node_id(self, connect: ConnectParams) -> str:
        if connect.device is not None and connect.device.id:
            return connect.device.id
        return connect.client.id

    def _resolve_presented_token(self, connect: ConnectParams) -> Optional[str]:
        if connect.auth is None:
            return None
        return connect.auth.token or connect.auth.deviceToken or connect.auth.bootstrapToken

    def _verify_device_signature(self, connect: ConnectParams, token: Optional[str]) -> bool:
        if connect.device is None:
            return False
        payload_v3 = build_device_auth_payload_v3(
            device_id=connect.device.id,
            client_id=connect.client.id,
            client_mode=connect.client.mode,
            role=connect.role or "node",
            scopes=list(connect.scopes or []),
            signed_at_ms=connect.device.signedAt,
            token=token,
            nonce=connect.device.nonce,
            platform=connect.client.platform,
            device_family=connect.client.deviceFamily,
        )
        if verify_device_signature(connect.device.publicKey, payload_v3, connect.device.signature):
            return True
        payload_v2 = build_device_auth_payload(
            device_id=connect.device.id,
            client_id=connect.client.id,
            client_mode=connect.client.mode,
            role=connect.role or "node",
            scopes=list(connect.scopes or []),
            signed_at_ms=connect.device.signedAt,
            token=token,
            nonce=connect.device.nonce,
        )
        return verify_device_signature(connect.device.publicKey, payload_v2, connect.device.signature)

    def _create_pending_pair(self, node_id: str, kind: str) -> str:
        request_id = str(uuid4())
        self._pending_pairs_by_request_id[request_id] = _PendingPairing(
            request_id=request_id,
            node_id=node_id,
            kind=kind,
            created_at_ms=int(time.time() * 1000),
        )
        return request_id

    async def _emit_callbacks(self, callbacks: list[Callable[..., Any]], *args: Any, **kwargs: Any) -> None:
        for callback in callbacks:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                await result

    def _error_response(
        self,
        request_id: str,
        *,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "res",
            "id": request_id,
            "ok": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if details:
            payload["error"]["details"] = details
        return payload


RabbitR1Bridge = RabbitR1NodeBridge

__all__ = [
    "RabbitR1Bridge",
    "RabbitR1BridgeConfig",
    "RabbitR1NodeBridge",
    "RabbitR1NodeContext",
]


import contextlib
