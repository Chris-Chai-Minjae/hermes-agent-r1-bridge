# OpenClaw Protocol Port Plan

This package is the first Hermes-side port of the OpenClaw gateway contract.
It is intentionally limited to the bootstrap path Hermes needs before a full
adapter lands.

## Package layout

- `models.py`
  - Pydantic wire models for `connect`, `connect.challenge`, `hello-ok`, and
    the `node.pair.*` request/result/event subset.
- `device_identity.py`
  - Ed25519 identity storage, SHA-256 device-id derivation, base64url public-key
    normalization, and sign/verify helpers compatible with OpenClaw.
- `device_auth.py`
  - Exact `v2` / `v3` device-auth payload builders plus a helper that emits the
    signed `device` object for the `connect` request.

## Handshake strategy

1. Open the WebSocket.
2. Wait for the server event `connect.challenge`.
3. Build the device signature payload with the server nonce.
   - Prefer `v3`.
   - Keep `v2` available as a fallback for compatibility testing.
4. Send `connect` with:
   - negotiated protocol range
   - `client`
   - `role`
   - `scopes`
   - declared node `caps` / `commands`
   - `auth`
   - signed `device`
5. Validate the `hello-ok` response and persist any returned `auth.deviceToken`.

## Pairing strategy

There are two distinct trust flows in OpenClaw and Hermes should keep them
separate:

- Device pairing:
  - gates the WebSocket handshake for new device identities
  - is what `../r1-openclaw.sh` currently auto-approves through `devices approve`
- Node pairing:
  - uses `node.pair.request` / `node.pair.approve` / `node.pair.verify`
  - controls node trust and issued node tokens
  - as documented in OpenClaw's `docs/gateway/pairing.md`, node commands are
    gated by node pairing starting on `2026-03-31`

That means the Rabbit R1 bridge likely needs both of these truths in mind:

- initial transport bootstrap is still token/device-auth driven
- node-command exposure after connect may still require the separate
  `node.pair.*` flow if Hermes wants behavior parity with current OpenClaw

## Suggested next implementation step

Add a dedicated adapter module that:

1. consumes the QR payload from `../r1-openclaw.sh`
2. performs the `connect.challenge` -> signed `connect` -> `hello-ok` loop
3. detects whether Hermes only needs device-level connectivity or also needs
   node-pair orchestration for command visibility
