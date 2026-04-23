# Rabbit R1 Node Bridge Design

## Boundary

- `gateway/rabbit_r1_node_bridge.py`
  - OpenClaw WebSocket protocol endpoint for Rabbit R1
  - owns handshake, device auth, device/node pairing state, node session state
- `gateway/platforms/rabbit_r1.py`
  - thin Hermes `BasePlatformAdapter` wrapper
  - only sees `nodeId`, transcript text, disconnect events, and outbound send helpers

## Public API

```python
await bridge.start()
await bridge.stop()

bridge.on_transcript(callback)
bridge.on_disconnect(callback)
bridge.on_pairing_required(callback)

await bridge.send_text(node_id, text)
await bridge.send_audio(node_id, audio_path, mime_type="audio/mpeg")
await bridge.send_typing(node_id)
```

All external methods use `nodeId` only.

Internal-only state:

- `deviceId`
- `publicKey`
- pairing `requestId`
- OpenClaw `sessionKey`
- caps / commands / permissions

## State machine

1. `TCP_ACCEPTED`
2. `CHALLENGE_SENT`
3. `CONNECT_RECEIVED`
4. `DEVICE_AUTH_VALIDATED`
5. `PAIRING_CHECK`
6. `READY`
7. `DISCONNECTED`

Detailed transitions:

- `CHALLENGE_SENT` -> `CONNECT_RECEIVED`
  - wait for `connect`
- `CONNECT_RECEIVED` -> `DEVICE_AUTH_VALIDATED`
  - validate protocol range
  - validate token auth
  - validate Ed25519 device signature with v3 payload
  - allow v2 fallback for compatibility testing
- `DEVICE_AUTH_VALIDATED` -> `PAIRING_CHECK`
  - resolve public `nodeId = connect.device.id ?? connect.client.id`
- `PAIRING_CHECK` -> `READY`
  - if device pair + node pair already approved, return `hello-ok`
  - if `auto_approve_pairing=True`, approve both stores in-process
  - otherwise return pairing-required error and surface callback
- `READY`
  - accept `node.event`
  - for L1 only `voice.transcript` is consumed

## Inbound L1 surface

- Method: `node.event`
- Supported event: `voice.transcript`
- Minimal payload fields:
  - `text`
  - optional `sessionKey`
  - optional dedupe metadata (`eventId`, `callId`, `sequence`, `timestamp`)

Bridge behavior:

- parse transcript payload
- update internal node session `session_key`
- call the registered Hermes callback:

```python
callback(node_ctx, text, is_voice=True, request_id=..., session_key=...)
```

## Outbound L1 surface

Current bridge sends Hermes replies over the standard OpenClaw event envelope:

- event: `node.invoke.request`

Provisional command names:

- `rabbit_r1.send_text`
- `rabbit_r1.send_audio`

Rationale:

- stays on the existing node event transport
- keeps Hermes adapter logic simple
- avoids pretending canvas or general OpenClaw node commands are already implemented

## Pairing UX proposal

Recommended L1 flow:

1. first unpaired R1 connect creates pending device/node entries inside the bridge
2. bridge calls `on_pairing_required(node_id, request_id)`
3. Hermes CLI/wrapper prompts:
   - `Approve Rabbit R1 device <node_id>? [y/N]`
4. on approval, bridge persists both pair stores and the next connect succeeds

This keeps approval local to Hermes and avoids depending on the OpenClaw macOS/UI flow.

## TODO error codes

Use explicit bridge-side error codes for not-yet-implemented surfaces:

- `NODE_INVOKE_UNSUPPORTED`
- `CANVAS_UNSUPPORTED`
- `EXEC_APPROVAL_UNSUPPORTED`

These should be returned as normal response-frame errors:

```json
{
  "type": "res",
  "id": "req-123",
  "ok": false,
  "error": {
    "code": "CANVAS_UNSUPPORTED",
    "message": "unsupported node event: canvas.navigate"
  }
}
```

## Important protocol note

OpenClaw's current docs split trust in two layers:

- device pairing gates initial device identity trust
- node pairing gates node trust and, since `2026-03-31`, node command exposure

`../r1-openclaw.sh` still auto-approves device pairing (`devices approve`), not
`node.pair.*`. Hermes should preserve that distinction even if both stores are
hidden behind the bridge's single public `nodeId` view.
