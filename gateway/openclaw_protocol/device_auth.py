"""OpenClaw-compatible device-auth payload helpers."""

from __future__ import annotations

from typing import Optional

from .device_identity import DeviceIdentity, public_key_raw_base64url_from_pem, sign_device_payload
from .models import ConnectDeviceIdentity


def normalize_device_metadata_for_auth(value: Optional[str]) -> str:
    """Mirror OpenClaw's auth normalization: trim, then lowercase ASCII only."""
    if value is None:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    chars: list[str] = []
    for char in trimmed:
        if "A" <= char <= "Z":
            chars.append(chr(ord(char) + 32))
        else:
            chars.append(char)
    return "".join(chars)


def build_device_auth_payload(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: Optional[str] = None,
    nonce: str,
) -> str:
    scopes_blob = ",".join(scopes)
    token_value = token or ""
    return "|".join(
        [
            "v2",
            device_id,
            client_id,
            client_mode,
            role,
            scopes_blob,
            str(signed_at_ms),
            token_value,
            nonce,
        ]
    )


def build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: Optional[str] = None,
    nonce: str,
    platform: Optional[str] = None,
    device_family: Optional[str] = None,
) -> str:
    scopes_blob = ",".join(scopes)
    token_value = token or ""
    platform_value = normalize_device_metadata_for_auth(platform)
    device_family_value = normalize_device_metadata_for_auth(device_family)
    return "|".join(
        [
            "v3",
            device_id,
            client_id,
            client_mode,
            role,
            scopes_blob,
            str(signed_at_ms),
            token_value,
            nonce,
            platform_value,
            device_family_value,
        ]
    )


def build_signed_connect_device(
    *,
    identity: DeviceIdentity,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    nonce: str,
    token: Optional[str] = None,
    platform: Optional[str] = None,
    device_family: Optional[str] = None,
) -> ConnectDeviceIdentity:
    payload = build_device_auth_payload_v3(
        device_id=identity.device_id,
        client_id=client_id,
        client_mode=client_mode,
        role=role,
        scopes=scopes,
        signed_at_ms=signed_at_ms,
        token=token,
        nonce=nonce,
        platform=platform,
        device_family=device_family,
    )
    return ConnectDeviceIdentity(
        id=identity.device_id,
        publicKey=public_key_raw_base64url_from_pem(identity.public_key_pem),
        signature=sign_device_payload(identity.private_key_pem, payload),
        signedAt=signed_at_ms,
        nonce=nonce,
    )
