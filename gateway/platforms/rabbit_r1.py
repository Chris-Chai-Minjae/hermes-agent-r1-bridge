"""Rabbit R1 adapter backed by the OpenClaw node bridge."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.rabbit_r1_node_bridge import (
    RabbitR1Bridge,
    RabbitR1BridgeConfig,
    RabbitR1NodeContext,
)

logger = logging.getLogger(__name__)


def check_rabbit_r1_requirements() -> bool:
    """Return True when the bridge runtime dependencies are importable."""
    try:
        import aiohttp  # noqa: F401
    except Exception:
        return False
    return True


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    return bool(value)


class RabbitR1Adapter(BasePlatformAdapter):
    """Thin Hermes adapter over ``RabbitR1Bridge``."""

    platform = Platform.RABBIT_R1

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.RABBIT_R1)
        extra = config.extra or {}
        self._host = str(extra.get("host") or "0.0.0.0").strip() or "0.0.0.0"
        self._port = int(extra.get("port") or 18789)
        self._auth_token = str(config.token or extra.get("auth_token") or "").strip()
        self._auto_approve_pairing = _coerce_bool(extra.get("auto_approve_pairing"), False)
        self._default_session_key = (
            str(extra.get("default_session_key") or "agent:main:main").strip() or "agent:main:main"
        )
        self._bridge: Optional[RabbitR1Bridge] = None
        self._node_contexts: Dict[str, RabbitR1NodeContext] = {}
        self._pending_pairing_requests: Dict[str, str] = {}

    async def connect(self) -> bool:
        if not self._auth_token:
            logger.error("Rabbit R1: RABBIT_R1_AUTH_TOKEN is required")
            return False

        bridge = RabbitR1Bridge(
            RabbitR1BridgeConfig(
                host=self._host,
                port=self._port,
                auth_token=self._auth_token,
                auto_approve_pairing=self._auto_approve_pairing,
                default_session_key=self._default_session_key,
            )
        )
        bridge.on_transcript(self._on_transcript)
        bridge.on_disconnect(self._on_disconnect)
        bridge.on_pairing_required(self._on_pairing_required)
        try:
            await bridge.start()
        except Exception as exc:
            logger.error("Rabbit R1: failed to start bridge on %s:%s: %s", self._host, self._port, exc)
            return False

        self._bridge = bridge
        self._mark_connected()
        logger.info(
            "Rabbit R1: bridge listening on %s:%s (auto_approve_pairing=%s)",
            self._host,
            self._port,
            self._auto_approve_pairing,
        )
        return True

    async def disconnect(self) -> None:
        bridge = self._bridge
        self._bridge = None
        self._node_contexts.clear()
        self._pending_pairing_requests.clear()
        if bridge is not None:
            await bridge.stop()
        self._mark_disconnected()

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        bridge = self._bridge
        if bridge is None:
            return SendResult(success=False, error="Rabbit R1 bridge not connected")
        try:
            await bridge.send_text(chat_id, self.format_message(content))
            return SendResult(success=True, message_id=str(uuid4()))
        except KeyError:
            return SendResult(success=False, error=f"Unknown Rabbit R1 node: {chat_id}")
        except Exception as exc:
            logger.warning("Rabbit R1: send_text failed for %s: %s", chat_id, exc)
            return SendResult(success=False, error=str(exc))

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        bridge = self._bridge
        if bridge is None:
            return
        try:
            await bridge.send_typing(chat_id)
        except Exception as exc:
            logger.debug("Rabbit R1: send_typing failed for %s: %s", chat_id, exc)

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        bridge = self._bridge
        if bridge is None:
            return SendResult(success=False, error="Rabbit R1 bridge not connected")
        if caption:
            await self.send(chat_id=chat_id, content=caption, reply_to=reply_to, metadata=metadata)
        try:
            await bridge.send_audio(chat_id, str(audio_path), mime_type="audio/mpeg")
            return SendResult(success=True, message_id=str(uuid4()))
        except KeyError:
            return SendResult(success=False, error=f"Unknown Rabbit R1 node: {chat_id}")
        except Exception as exc:
            logger.warning("Rabbit R1: send_audio failed for %s: %s", chat_id, exc)
            return SendResult(success=False, error=str(exc))

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return SendResult(success=False, error="Rabbit R1 does not support document delivery in L1")

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return SendResult(success=False, error="Rabbit R1 does not support image delivery in L1")

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        **kwargs,
    ) -> SendResult:
        return SendResult(success=False, error="Rabbit R1 does not support video delivery in L1")

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        ctx = self._node_contexts.get(chat_id)
        if ctx is None:
            return {"name": chat_id, "type": "dm", "chat_id": chat_id}
        return {
            "name": ctx.display_name or ctx.node_id,
            "type": "dm",
            "chat_id": ctx.node_id,
        }

    def format_message(self, content: str) -> str:
        return content.strip()

    async def _on_transcript(
        self,
        node_ctx: RabbitR1NodeContext,
        text: str,
        *,
        is_voice: bool = True,
        request_id: Optional[str] = None,
        session_key: Optional[str] = None,
    ) -> None:
        self._node_contexts[node_ctx.node_id] = node_ctx
        source = self.build_source(
            chat_id=node_ctx.node_id,
            chat_name=node_ctx.display_name or node_ctx.node_id,
            chat_type="dm",
            user_id=node_ctx.node_id,
            user_name=node_ctx.display_name or "Rabbit R1",
        )
        event = MessageEvent(
            text=text or "",
            message_type=MessageType.VOICE if is_voice else MessageType.TEXT,
            source=source,
            message_id=str(request_id) if request_id else None,
            raw_message={
                "session_key": session_key or node_ctx.session_key,
                "node_context": {
                    "node_id": node_ctx.node_id,
                    "client_id": node_ctx.client_id,
                    "client_mode": node_ctx.client_mode,
                    "display_name": node_ctx.display_name,
                    "platform": node_ctx.platform,
                    "version": node_ctx.version,
                    "device_family": node_ctx.device_family,
                    "model_identifier": node_ctx.model_identifier,
                    "caps": list(node_ctx.caps),
                    "commands": list(node_ctx.commands),
                    "permissions": dict(node_ctx.permissions),
                    "remote_ip": node_ctx.remote_ip,
                    "connected_at_ms": node_ctx.connected_at_ms,
                },
            },
        )
        await self.handle_message(event)

    async def _on_disconnect(self, node_id: str) -> None:
        self._node_contexts.pop(node_id, None)
        self._pending_pairing_requests.pop(node_id, None)

    async def _on_pairing_required(self, node_id: str, request_id: str) -> None:
        self._pending_pairing_requests[node_id] = request_id
        logger.warning(
            "Rabbit R1: pairing required for node %s (request_id=%s). "
            "Current bridge public API does not expose approval yet; set "
            "RABBIT_R1_AUTO_APPROVE_PAIRING=true for local L1 bring-up.",
            node_id,
            request_id,
        )
