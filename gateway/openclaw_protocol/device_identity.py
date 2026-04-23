"""Ed25519 device identity helpers compatible with OpenClaw."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive_public_key_raw_from_pem(public_key_pem: str) -> bytes:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    spki_der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if len(spki_der) == len(ED25519_SPKI_PREFIX) + 32 and spki_der.startswith(ED25519_SPKI_PREFIX):
        return spki_der[len(ED25519_SPKI_PREFIX) :]
    return spki_der


def _fingerprint_public_key(public_key_pem: str) -> str:
    return hashlib.sha256(_derive_public_key_raw_from_pem(public_key_pem)).hexdigest()


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    public_key_pem: str
    private_key_pem: str


def _generate_identity() -> DeviceIdentity:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_key_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    ).decode("utf-8")
    return DeviceIdentity(
        device_id=_fingerprint_public_key(public_key_pem),
        public_key_pem=public_key_pem,
        private_key_pem=private_key_pem,
    )


def load_or_create_device_identity(file_path: str | Path) -> DeviceIdentity:
    path = Path(file_path)
    try:
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            device_id = parsed.get("deviceId")
            public_key_pem = parsed.get("publicKeyPem")
            private_key_pem = parsed.get("privateKeyPem")
            if (
                isinstance(device_id, str)
                and isinstance(public_key_pem, str)
                and isinstance(private_key_pem, str)
            ):
                derived_device_id = _fingerprint_public_key(public_key_pem)
                identity = DeviceIdentity(
                    device_id=derived_device_id,
                    public_key_pem=public_key_pem,
                    private_key_pem=private_key_pem,
                )
                if derived_device_id != device_id:
                    _persist_identity(path, identity)
                return identity
    except Exception:
        pass

    identity = _generate_identity()
    _persist_identity(path, identity)
    return identity


def _persist_identity(path: Path, identity: DeviceIdentity) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "deviceId": identity.device_id,
        "publicKeyPem": identity.public_key_pem,
        "privateKeyPem": identity.private_key_pem,
    }
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def sign_device_payload(private_key_pem: str, payload: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("expected an Ed25519 private key")
    return _base64url_encode(private_key.sign(payload.encode("utf-8")))


def normalize_device_public_key_base64url(public_key: str) -> Optional[str]:
    try:
        if "BEGIN" in public_key:
            return _base64url_encode(_derive_public_key_raw_from_pem(public_key))
        raw = _base64url_decode(public_key)
        return _base64url_encode(raw) if raw else None
    except Exception:
        return None


def derive_device_id_from_public_key(public_key: str) -> Optional[str]:
    try:
        raw = (
            _derive_public_key_raw_from_pem(public_key)
            if "BEGIN" in public_key
            else _base64url_decode(public_key)
        )
        return hashlib.sha256(raw).hexdigest() if raw else None
    except Exception:
        return None


def public_key_raw_base64url_from_pem(public_key_pem: str) -> str:
    return _base64url_encode(_derive_public_key_raw_from_pem(public_key_pem))


def verify_device_signature(public_key: str, payload: str, signature_base64url: str) -> bool:
    try:
        if "BEGIN" in public_key:
            public_obj = serialization.load_pem_public_key(public_key.encode("utf-8"))
        else:
            public_obj = Ed25519PublicKey.from_public_bytes(_base64url_decode(public_key))
        if not isinstance(public_obj, Ed25519PublicKey):
            return False
        public_obj.verify(
            _base64url_decode(signature_base64url),
            payload.encode("utf-8"),
        )
        return True
    except Exception:
        return False
