import asyncio
from types import SimpleNamespace

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType


class _FakeBridge:
    instances = []

    def __init__(self, config):
        self.config = config
        self.transcript_callbacks = []
        self.disconnect_callbacks = []
        self.pairing_callbacks = []
        self.sent_text = []
        self.sent_audio = []
        self.typing = []
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def on_transcript(self, callback):
        self.transcript_callbacks.append(callback)
        return callback

    def on_disconnect(self, callback):
        self.disconnect_callbacks.append(callback)
        return callback

    def on_pairing_required(self, callback):
        self.pairing_callbacks.append(callback)
        return callback

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send_text(self, node_id, text):
        self.sent_text.append((node_id, text))

    async def send_audio(self, node_id, audio_path, mime_type="audio/mpeg"):
        self.sent_audio.append((node_id, audio_path, mime_type))

    async def send_typing(self, node_id):
        self.typing.append(node_id)


def _make_adapter(monkeypatch):
    from gateway.platforms import rabbit_r1 as rabbit_mod
    from gateway.platforms.rabbit_r1 import RabbitR1Adapter

    _FakeBridge.instances.clear()
    monkeypatch.setattr(rabbit_mod, "RabbitR1Bridge", _FakeBridge)
    config = PlatformConfig(enabled=True, token="r1-secret")
    config.extra = {
        "host": "127.0.0.1",
        "port": 18789,
        "auto_approve_pairing": True,
        "default_session_key": "agent:main:test",
    }
    return RabbitR1Adapter(config)


@pytest.mark.asyncio
async def test_connect_registers_bridge_callbacks(monkeypatch):
    adapter = _make_adapter(monkeypatch)

    ok = await adapter.connect()

    assert ok is True
    assert adapter.is_connected is True
    bridge = _FakeBridge.instances[-1]
    assert bridge.started is True
    assert len(bridge.transcript_callbacks) == 1
    assert len(bridge.disconnect_callbacks) == 1
    assert len(bridge.pairing_callbacks) == 1


@pytest.mark.asyncio
async def test_transcript_callback_builds_voice_message_event(monkeypatch):
    adapter = _make_adapter(monkeypatch)
    await adapter.connect()
    captured = []

    async def handler(event):
        captured.append(event)
        return None

    adapter.set_message_handler(handler)
    bridge = _FakeBridge.instances[-1]
    node_ctx = SimpleNamespace(
        node_id="node-123",
        client_id="rabbit-r1",
        client_mode="node",
        display_name="Rabbit R1",
        platform="rabbitos",
        version="1.0.0",
        device_family="rabbit-r1",
        model_identifier="r1",
        session_key="agent:main:test",
        remote_ip="192.0.2.10",
        caps=["voice"],
        commands=["rabbit_r1.send_text"],
        permissions={"voice": True},
        connected_at_ms=1234,
    )

    await bridge.transcript_callbacks[0](
        node_ctx,
        "hello from rabbit",
        is_voice=True,
        request_id="evt-1",
        session_key="agent:main:test",
    )
    await asyncio.sleep(0)
    if adapter._background_tasks:
        await asyncio.gather(*list(adapter._background_tasks))

    assert len(captured) == 1
    event = captured[0]
    assert event.text == "hello from rabbit"
    assert event.message_type == MessageType.VOICE
    assert event.source.chat_id == "node-123"
    assert event.source.user_id == "node-123"
    assert event.source.chat_name == "Rabbit R1"
    assert event.message_id == "evt-1"
    assert event.raw_message["session_key"] == "agent:main:test"


@pytest.mark.asyncio
async def test_send_and_send_voice_delegate_to_bridge(monkeypatch, tmp_path):
    adapter = _make_adapter(monkeypatch)
    await adapter.connect()
    bridge = _FakeBridge.instances[-1]

    text_result = await adapter.send("node-123", "hello")
    audio_path = tmp_path / "reply.mp3"
    audio_path.write_bytes(b"mp3")
    voice_result = await adapter.send_voice("node-123", str(audio_path))

    assert text_result.success is True
    assert bridge.sent_text == [("node-123", "hello")]
    assert voice_result.success is True
    assert bridge.sent_audio == [("node-123", str(audio_path), "audio/mpeg")]
