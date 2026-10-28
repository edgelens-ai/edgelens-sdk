# Platform API Reference

The EdgeLens platform API is a REST/JSON service at
`https://api.edgelens.ai`. All endpoints are versioned under `/v1`.

The framework SDKs (`edgelens`, `@edgelens/core`, `xk6-edgelens`,
`pytest-edgelens`, `robotframework-edgelens`) wrap this surface — most
tests should never touch raw HTTP. Reference it when:

- Debugging an SDK call that's returning an unexpected status code.
- Writing a brand-new SDK in a language we don't yet ship.
- Building a one-off curl script for CI.

The OpenAPI spec is served at `/api/spec.json` (the interactive docs
pages are not served). The reference below
covers the public, customer-facing endpoints; the portal-only `/v1/accounts`
routes are not part of the public API.

## Authentication

Every request needs a Bearer token:

```http
Authorization: Bearer el_live_xxxxxxxxxxxxxxxxxxxx
```

Keys are minted in the portal. The plaintext is returned exactly once
at creation; the API only stores a HMAC-SHA256 hash. A revoked key
returns `401 API key has been revoked`.

## Rate limits

- Per-key token bucket: 5 req/s with a burst of 20 by default. A 429
  carries `Retry-After` (whole seconds, at least 1).
- Per source IP, before authentication, on `/v1/*`: at most 10 requests
  in a one-second window. A 429 from this limit carries `Retry-After: 1`;
  pause a full second before retrying, because requests sent while
  limited keep the window closed. (`/health` and `/api/spec.json` are
  exempt.)
- Body size is capped: `/v1/*` at 32 MiB, anything else at 64 KiB.

## Error shape

Every error response is JSON:

```json
{ "detail": "Session sess_abc123 is in state flashing" }
```

Status code semantics across the API:

| Code | When |
|---|---|
| 200 | Success. |
| 400 | Malformed request — bad header, invalid URL, etc. |
| 401 | Missing / invalid / revoked Bearer token. |
| 403 | Authenticated, but the key's scope doesn't permit this device_type, OS, or duration. |
| 404 | Resource not found, **or** you don't own it (we don't leak existence by returning 403). |
| 409 | State conflict — session not in `ready` state, device already in use, etc. |
| 410 | Session was released; the operation is no longer valid. |
| 413 | Request body exceeded the size cap. |
| 422 | Pydantic validation failed — bad field type, unknown field, out-of-range value. |
| 429 | Rate-limited, or `max_concurrent_sessions` exceeded. Honor `Retry-After`. |

## Sessions

A session is one device allocation for one customer. It owns the
device for the duration of the lifecycle. Its states are `pending`,
`allocating`, `flashing`, `ready`, `released`, `expired` and `error`.
`released` follows a `DELETE`; `expired` follows the session's
`expires_at`; neither follows the other. Every device operation runs
against a session id.

### `POST /v1/sessions` — create a session

```http
POST /v1/sessions
Authorization: Bearer el_live_xxx
Content-Type: application/json

{
  "device_type": "recamera-2002",
  "os": "stock-os",
  "image_version": "latest",
  "timeout": 3600
}
```

**Request fields:**
- `device_type` — `"recamera-2002"` (only supported type today).
- `os` — `"stock-os"` (reCamera firmware) or `"recamagined"` (SSH-only).
- `image_version` — `"latest"` or a pinned `[A-Za-z0-9._-]{1,64}` tag.
- `timeout` — session duration cap in seconds (60–86400).

**Response 200:**

```json
{
  "id": "sess_AbCdEf123456",
  "status": "flashing",
  "device": null,
  "created_at": "2026-06-14T18:42:13Z",
  "expires_at": "2026-06-14T19:42:13Z",
  "ready_at": null,
  "released_at": null,
  "returned_at": null
}
```

Poll `GET /v1/sessions/{id}` until `status` is `ready`; `device` will be populated then.

### `GET /v1/sessions/{id}` — poll status

Returns the same shape as create. Common transitions to watch:

- `pending` → `allocating` → `flashing` — flash in progress.
- `flashing` → `ready` — device is up; `device` field is now populated.
- `ready` → `released` — on `DELETE /v1/sessions/{id}`.
- `ready` → `expired` — when `expires_at` is reached.
- any → `error` — `error` field carries the reason.

### `DELETE /v1/sessions/{id}` — release the device

Idempotent; calling on an already-released session returns 200 with
the existing terminal state.

### Device operations (require `status=ready`)

All of these require the session to be `READY` and owned by the calling
key. Cross-key access returns 404 (existence is not leaked).

| Endpoint | Purpose |
|---|---|
| `POST /v1/sessions/{id}/exec` | Run a shell command via SSH; returns stdout/stderr/exit_code. `command` capped at 4 KiB; `timeout` 1–600 s. |
| `POST /v1/sessions/{id}/deploy` | Push a model + optional config and extra files to the camera, on `stock-os` and `recamagined`. Send `multipart/form-data` streaming the local file bytes; parts: `model` required, optional `config`, optional `file_0..file_N`. On `recamagined`, the model and each file land in `/userdata/Models/` under their base filenames, readable but not executable: `chmod +x` a deployed binary before running it. |
| `GET  /v1/sessions/{id}/info` | Hostname, hardware, OS version. |
| `GET  /v1/sessions/{id}/ssh` | SSH credentials (user/host/port/password). Access is audit-logged. |
| `GET  /v1/sessions/{id}/stream` | WebSocket URL for the camera stream (`stock-os` only). |
| `POST /v1/sessions/{id}/display/play` | Play a video on the on-device display. `source` URL must be public. |
| `POST /v1/sessions/{id}/display/show` | Show a still image. |
| `POST /v1/sessions/{id}/display/stop` | Stop playback. |
| `GET  /v1/sessions/{id}/display/status` | Current display state. |
| `POST /v1/sessions/{id}/inference/start` | Start the built-in inference engine (`stock-os` only). |
| `POST /v1/sessions/{id}/inference/stop` | Stop it. |
| `GET  /v1/sessions/{id}/inference/once` | One frame of detections. |
| `GET  /v1/sessions/{id}/inference/stats` | Live fps + latency rollup. |
| `POST /v1/sessions/{id}/inference/results` | Run for `duration_s` seconds and return aggregated stats. |

### Outbound URL validation

For any endpoint that accepts a URL field — `display/play.source`,
`display/show.source` — the API:

1. Rejects non-`http(s)` schemes (422).
2. Resolves the host and rejects any private / loopback / link-local /
   reserved IP (400 with `private` in the detail).

## Session lifecycle diagram

```
                  POST /v1/sessions
                          │
                          ▼
                    ┌─────────────┐
                    │   pending   │
                    └─────────────┘
                          │  platform assigns a device
                          ▼
                    ┌─────────────┐
                    │  allocating │
                    └─────────────┘
                          │  device reserved for your session
                          ▼
                    ┌─────────────┐
                    │   flashing  │
                    └─────────────┘
                          │
              ┌───────────┴──────────┐
              ▼                      ▼
       ┌─────────────┐         ┌─────────────┐
       │    ready    │         │    error    │
       └─────────────┘         └─────────────┘
              │  ops run here
              │
       ┌──────┴────────────────────┐
       │ DELETE /v1/sessions/{id}  │ expires_at reached
       ▼                           ▼
┌─────────────┐             ┌─────────────┐
│   released  │             │   expired   │
└─────────────┘             └─────────────┘
```

`released` and `expired` are both terminal.

`released_at - ready_at` is the billable window. `returned_at` is a
timestamp, not a state: it marks when the device finished its
post-session wipe and is back in the pool.

## Versioning

The platform API is versioned by URL prefix (`/v1`). Breaking changes
land on a new prefix (`/v2`) with both served in parallel during the
deprecation window. Non-breaking additions (new optional fields, new
endpoints) ship to `/v1` without a major bump.

Stable surface = anything documented above.
