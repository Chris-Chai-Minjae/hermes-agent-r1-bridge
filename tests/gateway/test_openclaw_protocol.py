"""Tests for the Hermes-side OpenClaw protocol port."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.openclaw_protocol import (
    ConnectChallengeEvent,
    DevicePairRequestedEvent,
    ErrorCodes,
    GatewayClientInfo,
    GatewayClientIds,
    GatewayClientModes,
    HelloOkResponseFrame,
    NodeInvokeRequestEvent,
    NodePendingDrainResult,
    NodePairRequestResult,
    NodePairResolvedEvent,
    PROTOCOL_VERSION,
    ShutdownEvent,
    TickEvent,
    build_device_auth_payload,
    build_device_auth_payload_v3,
    build_signed_connect_device,
    derive_device_id_from_public_key,
    load_or_create_device_identity,
    normalize_device_metadata_for_auth,
    parse_gateway_frame,
    public_key_raw_base64url_from_pem,
    verify_device_signature,
)


def test_device_auth_payload_vectors_match_openclaw() -> None:
    assert (
        build_device_auth_payload(
            device_id="dev-1",
            client_id="openclaw-macos",
            client_mode="ui",
            role="operator",
            scopes=["operator.admin", "operator.read"],
            signed_at_ms=1_700_000_000_000,
            token=None,
            nonce="nonce-abc",
        )
        == "v2|dev-1|openclaw-macos|ui|operator|operator.admin,operator.read|1700000000000||nonce-abc"
    )
    assert (
        build_device_auth_payload_v3(
            device_id="dev-1",
            client_id="openclaw-macos",
            client_mode="ui",
            role="operator",
            scopes=["operator.admin", "operator.read"],
            signed_at_ms=1_700_000_000_000,
            token="tok-123",
            nonce="nonce-abc",
            platform="  IOS  ",
            device_family="  iPhone  ",
        )
        == "v3|dev-1|openclaw-macos|ui|operator|operator.admin,operator.read|1700000000000|tok-123|nonce-abc|ios|iphone"
    )
    assert (
        build_device_auth_payload_v3(
            device_id="dev-2",
            client_id="openclaw-ios",
            client_mode="ui",
            role="operator",
            scopes=["operator.read"],
            signed_at_ms=1_700_000_000_001,
            nonce="nonce-def",
        )
        == "v3|dev-2|openclaw-ios|ui|operator|operator.read|1700000000001||nonce-def||"
    )


def test_metadata_normalization_keeps_non_ascii_behavior() -> None:
    assert normalize_device_metadata_for_auth("  İOS  ") == "İos"
    assert normalize_device_metadata_for_auth("  MAC  ") == "mac"
    assert normalize_device_metadata_for_auth(None) == ""


def test_device_identity_roundtrip_and_signature_verification(tmp_path) -> None:
    identity_path = tmp_path / "device.json"
    identity = load_or_create_device_identity(identity_path)
    assert identity.device_id == derive_device_id_from_public_key(identity.public_key_pem)

    payload = build_device_auth_payload_v3(
        device_id=identity.device_id,
        client_id="openclaw-ios",
        client_mode="node",
        role="node",
        scopes=[],
        signed_at_ms=1_700_000_000_002,
        token="secret-token",
        nonce="nonce-r1",
        platform="ios",
        device_family="Rabbit R1",
    )
    connect_device = build_signed_connect_device(
        identity=identity,
        client_id="openclaw-ios",
        client_mode="node",
        role="node",
        scopes=[],
        signed_at_ms=1_700_000_000_002,
        token="secret-token",
        nonce="nonce-r1",
        platform="ios",
        device_family="Rabbit R1",
    )
    assert connect_device.id == identity.device_id
    assert connect_device.publicKey == public_key_raw_base64url_from_pem(identity.public_key_pem)
    assert verify_device_signature(connect_device.publicKey, payload, connect_device.signature) is True


def test_frame_parser_handles_challenge_and_hello_ok_shapes() -> None:
    challenge = parse_gateway_frame(
        {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": "nonce-123", "ts": 1_737_264_000_000},
        }
    )
    assert isinstance(challenge, ConnectChallengeEvent)
    assert challenge.payload.nonce == "nonce-123"

    hello = parse_gateway_frame(
        {
            "type": "res",
            "id": "connect-1",
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 3,
                "server": {"version": "2026.4.22", "connId": "conn-1"},
                "features": {
                    "methods": ["node.pair.request", "node.pair.verify"],
                    "events": ["connect.challenge", "node.pair.requested"],
                },
                "snapshot": {
                    "presence": [],
                    "health": {},
                    "stateVersion": {"presence": 0, "health": 0},
                    "uptimeMs": 42,
                },
                "policy": {
                    "maxPayload": 26_214_400,
                    "maxBufferedBytes": 52_428_800,
                    "tickIntervalMs": 15_000,
                },
                "auth": {
                    "deviceToken": "device-token-1",
                    "role": "node",
                    "scopes": [],
                },
            },
        }
    )
    assert isinstance(hello, HelloOkResponseFrame)
    assert hello.payload.auth is not None
    assert hello.payload.auth.deviceToken == "device-token-1"

    tick = parse_gateway_frame(
        {
            "type": "event",
            "event": "tick",
            "payload": {"ts": 1_737_264_000_123},
        }
    )
    assert isinstance(tick, TickEvent)
    assert tick.payload.ts == 1_737_264_000_123

    shutdown = parse_gateway_frame(
        {
            "type": "event",
            "event": "shutdown",
            "payload": {"reason": "restart", "restartExpectedMs": 5000},
        }
    )
    assert isinstance(shutdown, ShutdownEvent)
    assert shutdown.payload.reason == "restart"


def test_node_pair_models_cover_request_result_and_resolution_event() -> None:
    result = NodePairRequestResult.model_validate(
        {
            "status": "pending",
            "created": True,
            "request": {
                "requestId": "req-1",
                "nodeId": "node-1",
                "platform": "ios",
                "commands": ["canvas.snapshot", "system.run"],
                "silent": False,
                "ts": 1_737_264_000_001,
            },
        }
    )
    assert result.request.nodeId == "node-1"
    assert result.request.commands == ["canvas.snapshot", "system.run"]

    resolved = NodePairResolvedEvent.model_validate(
        {
            "type": "event",
            "event": "node.pair.resolved",
            "payload": {
                "requestId": "req-1",
                "nodeId": "node-1",
                "decision": "approved",
                "ts": 1_737_264_000_100,
            },
        }
    )
    assert resolved.payload.decision == "approved"


def test_device_pair_and_node_invoke_related_models_cover_l1_inventory() -> None:
    device_pair = DevicePairRequestedEvent.model_validate(
        {
            "type": "event",
            "event": "device.pair.requested",
            "payload": {
                "requestId": "req-device-1",
                "deviceId": "device-1",
                "publicKey": "pubkey-1",
                "clientId": "openclaw-ios",
                "clientMode": "node",
                "role": "node",
                "roles": ["node"],
                "scopes": [],
                "ts": 1_737_264_000_200,
            },
        }
    )
    assert device_pair.payload.deviceId == "device-1"

    invoke_request = NodeInvokeRequestEvent.model_validate(
        {
            "type": "event",
            "event": "node.invoke.request",
            "payload": {
                "id": "invoke-1",
                "nodeId": "node-1",
                "command": "rabbit_r1.send_text",
                "paramsJSON": '{"text":"hi"}',
                "timeoutMs": 1000,
                "idempotencyKey": "idem-1",
            },
        }
    )
    assert invoke_request.payload.command == "rabbit_r1.send_text"

    pending = NodePendingDrainResult.model_validate(
        {
            "nodeId": "node-1",
            "revision": 2,
            "items": [
                {
                    "id": "pending-1",
                    "type": "status.request",
                    "priority": "default",
                    "createdAtMs": 1_737_264_000_300,
                    "expiresAtMs": None,
                    "payload": {"source": "operator"},
                }
            ],
            "hasMore": False,
        }
    )
    assert pending.items[0].type == "status.request"


def test_protocol_version_and_official_error_codes_are_available() -> None:
    assert PROTOCOL_VERSION == 3
    assert ErrorCodes.INVALID_REQUEST == "INVALID_REQUEST"
    assert ErrorCodes.UNAVAILABLE == "UNAVAILABLE"
    assert GatewayClientIds.IOS_APP == "openclaw-ios"
    assert GatewayClientModes.NODE == "node"


def test_gateway_client_info_rejects_invalid_client_id_and_mode() -> None:
    with pytest.raises(ValidationError):
        GatewayClientInfo.model_validate(
            {
                "id": "rabbit-r1-custom",
                "version": "1.0.0",
                "platform": "rabbitos",
                "mode": "custom-node",
            }
        )
