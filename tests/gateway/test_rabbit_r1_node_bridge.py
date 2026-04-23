"""Tests for the Rabbit R1 bridge seam."""

from __future__ import annotations

import asyncio
import json
import socket
from types import SimpleNamespace

import pytest

from gateway.openclaw_protocol import ConnectAuth, ConnectDeviceIdentity, ConnectParams, ConnectRequestFrame, GatewayClientInfo
from gateway.openclaw_protocol import (
    GatewayClientIds,
    GatewayClientModes,
    build_signed_connect_device,
    load_or_create_device_identity,
)
from gateway.rabbit_r1_node_bridge import (
    ERROR_CANVAS_UNSUPPORTED,
    ERROR_DEVICE_PAIRING_REQUIRED,
    ERROR_EXEC_APPROVAL_UNSUPPORTED,
    ERROR_NODE_INVOKE_UNSUPPORTED,
    RabbitR1BridgeConfig,
    RabbitR1NodeBridge,
)


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def test_bridge_resolves_public_node_id_from_device_identity() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig())
    connect = ConnectParams(
        minProtocol=3,
        maxProtocol=3,
        client=GatewayClientInfo(
            id=GatewayClientIds.IOS_APP,
            version="1.0.0",
            platform="android",
            mode=GatewayClientModes.NODE,
        ),
        role="node",
        scopes=[],
        device=ConnectDeviceIdentity(
            id="device-node-id",
            publicKey="pub",
            signature="sig",
            signedAt=1,
            nonce="nonce",
        ),
    )
    assert bridge._resolve_node_id(connect) == "device-node-id"


def test_bridge_falls_back_to_client_id_when_device_identity_is_missing() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig())
    connect = ConnectParams(
        minProtocol=3,
        maxProtocol=3,
        client=GatewayClientInfo(
            id=GatewayClientIds.IOS_APP,
            version="1.0.0",
            platform="android",
            mode=GatewayClientModes.NODE,
        ),
        role="node",
        scopes=[],
    )
    assert bridge._resolve_node_id(connect) == GatewayClientIds.IOS_APP


def test_bridge_requires_pairing_when_auto_approve_is_disabled() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig(auto_approve_pairing=False))
    connect = ConnectParams(
        minProtocol=3,
        maxProtocol=3,
        client=GatewayClientInfo(
            id=GatewayClientIds.IOS_APP,
            version="1.0.0",
            platform="android",
            mode=GatewayClientModes.NODE,
        ),
        role="node",
        scopes=[],
        auth=ConnectAuth(token="secret"),
    )
    error = asyncio.run(bridge._ensure_pairing(GatewayClientIds.IOS_APP, connect))
    assert error is not None
    assert error["code"] == ERROR_DEVICE_PAIRING_REQUIRED


def test_bridge_auto_approves_device_and_node_pairs_when_enabled() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig(auto_approve_pairing=True))
    connect = ConnectParams(
        minProtocol=3,
        maxProtocol=3,
        client=GatewayClientInfo(
            id=GatewayClientIds.IOS_APP,
            version="1.0.0",
            platform="android",
            mode=GatewayClientModes.NODE,
        ),
        role="node",
        scopes=[],
        auth=ConnectAuth(token="secret"),
    )
    error = asyncio.run(bridge._ensure_pairing(GatewayClientIds.IOS_APP, connect))
    assert error is None
    assert GatewayClientIds.IOS_APP in bridge._device_pairs_by_node_id
    assert GatewayClientIds.IOS_APP in bridge._node_pairs_by_node_id


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _register_connected_node(bridge: RabbitR1NodeBridge, node_id: str = "rabbit-node") -> _FakeWs:
    ws = _FakeWs()
    connect = ConnectParams(
        minProtocol=3,
        maxProtocol=3,
        client=GatewayClientInfo(
            id=GatewayClientIds.IOS_APP,
            version="1.0.0",
            platform="android",
            mode=GatewayClientModes.NODE,
        ),
        role="node",
        scopes=[],
    )
    context = bridge._build_node_context(SimpleNamespace(remote="127.0.0.1"), node_id, connect)
    bridge._connections_by_node_id[node_id] = SimpleNamespace(ws=ws, context=context)
    return ws


def test_bridge_rejects_non_node_event_methods_with_explicit_error_code() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig())
    ws = _register_connected_node(bridge)

    asyncio.run(
        bridge._handle_message(
            "rabbit-node",
            json.dumps(
                {
                    "type": "req",
                    "id": "req-1",
                    "method": "node.pending.drain",
                    "params": {},
                }
            ),
        )
    )

    assert ws.sent == [
        {
            "type": "res",
            "id": "req-1",
            "ok": False,
            "error": {
                "code": ERROR_NODE_INVOKE_UNSUPPORTED,
                "message": "unsupported method: node.pending.drain",
            },
        }
    ]


def test_bridge_rejects_unsupported_canvas_events_with_canvas_error_code() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig())
    ws = _register_connected_node(bridge)

    asyncio.run(
        bridge._handle_message(
            "rabbit-node",
            json.dumps(
                {
                    "type": "req",
                    "id": "req-2",
                    "method": "node.event",
                    "params": {
                        "event": "canvas.navigate",
                        "payload": {"url": "https://example.com"},
                    },
                }
            ),
        )
    )

    assert ws.sent == [
        {
            "type": "res",
            "id": "req-2",
            "ok": False,
            "error": {
                "code": ERROR_CANVAS_UNSUPPORTED,
                "message": "unsupported node event: canvas.navigate",
            },
        }
    ]


def test_bridge_rejects_unsupported_exec_events_with_exec_error_code() -> None:
    bridge = RabbitR1NodeBridge(RabbitR1BridgeConfig())
    ws = _register_connected_node(bridge)

    asyncio.run(
        bridge._handle_message(
            "rabbit-node",
            json.dumps(
                {
                    "type": "req",
                    "id": "req-3",
                    "method": "node.event",
                    "params": {
                        "event": "exec.approval.request",
                        "payload": {"command": "uname -a"},
                    },
                }
            ),
        )
    )

    assert ws.sent == [
        {
            "type": "res",
            "id": "req-3",
            "ok": False,
            "error": {
                "code": ERROR_EXEC_APPROVAL_UNSUPPORTED,
                "message": "unsupported node event: exec.approval.request",
            },
        }
    ]


def test_bridge_contract_flow_connect_voice_transcript_and_send_text(tmp_path) -> None:
    bridge = RabbitR1NodeBridge(
        RabbitR1BridgeConfig(
            host="127.0.0.1",
            port=_get_free_port(),
            auth_token="r1-secret",
            auto_approve_pairing=True,
            default_session_key="agent:main:e2e",
        )
    )
    captured: list[dict] = []

    @bridge.on_transcript
    async def _capture(node_ctx, text, *, is_voice=True, request_id=None, session_key=None):
        captured.append(
            {
                "node_id": node_ctx.node_id,
                "text": text,
                "is_voice": is_voice,
                "request_id": request_id,
                "session_key": session_key,
            }
        )

    identity = load_or_create_device_identity(tmp_path / "rabbit-device.json")
    challenge_msg = bridge._build_connect_challenge()
    assert challenge_msg["type"] == "event"
    assert challenge_msg["event"] == "connect.challenge"
    nonce = challenge_msg["payload"]["nonce"]

    signed_device = build_signed_connect_device(
        identity=identity,
        client_id=GatewayClientIds.IOS_APP,
        client_mode=GatewayClientModes.NODE,
        role="node",
        scopes=[],
        signed_at_ms=1_737_264_000_555,
        nonce=nonce,
        token="r1-secret",
        platform="rabbitos",
        device_family="Rabbit R1",
    )
    connect_frame = ConnectRequestFrame.model_validate(
        {
            "type": "req",
            "id": "connect-1",
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": GatewayClientIds.IOS_APP,
                    "version": "1.0.0",
                    "platform": "rabbitos",
                    "deviceFamily": "Rabbit R1",
                    "mode": GatewayClientModes.NODE,
                },
                "role": "node",
                "scopes": [],
                "caps": ["voice"],
                "commands": ["rabbit_r1.send_text"],
                "auth": {"token": "r1-secret"},
                "device": signed_device.model_dump(exclude_none=True),
            },
        }
    )

    bridge._validate_connect(connect_frame.params)
    node_id = bridge._resolve_node_id(connect_frame.params)
    pair_error = asyncio.run(bridge._ensure_pairing(node_id, connect_frame.params))
    assert pair_error is None

    ws = _FakeWs()
    context = bridge._build_node_context(SimpleNamespace(remote="127.0.0.1"), node_id, connect_frame.params)
    bridge._connections_by_node_id[node_id] = SimpleNamespace(ws=ws, context=context)

    hello_msg = bridge._hello_ok_response(connect_frame.id, context)
    assert hello_msg["type"] == "res"
    assert hello_msg["id"] == "connect-1"
    assert hello_msg["ok"] is True
    assert hello_msg["payload"]["type"] == "hello-ok"
    assert hello_msg["payload"]["auth"]["role"] == "node"

    asyncio.run(
        bridge._handle_message(
            node_id,
            json.dumps(
                {
                    "type": "req",
                    "id": "evt-1",
                    "method": "node.event",
                    "params": {
                        "event": "voice.transcript",
                        "payload": {
                            "text": "hello from rabbit e2e",
                            "sessionKey": "agent:main:e2e",
                            "eventId": "voice-1",
                        },
                    },
                }
            ),
        )
    )

    assert ws.sent[0] == {
        "type": "res",
        "id": "evt-1",
        "ok": True,
        "payload": {"accepted": True},
    }
    assert captured == [
        {
            "node_id": identity.device_id,
            "text": "hello from rabbit e2e",
            "is_voice": True,
            "request_id": "voice-1",
            "session_key": "agent:main:e2e",
        }
    ]

    asyncio.run(bridge.send_text(identity.device_id, "reply from hermes"))
    outbound = ws.sent[1]
    assert outbound["type"] == "event"
    assert outbound["event"] == "node.invoke.request"
    assert outbound["payload"]["nodeId"] == identity.device_id
    assert outbound["payload"]["command"] == "rabbit_r1.send_text"
    assert json.loads(outbound["payload"]["paramsJSON"]) == {"text": "reply from hermes"}
