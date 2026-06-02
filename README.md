# Eldes Gate — Home Assistant Integration

Unofficial Home Assistant integration for [Eldes](https://eldesalarms.com/)
GSM gate / garage-door controllers, talking to the same cloud backend
(`ea-gates-api.e-alarms.com`) the official **Eldes Gates** Android app uses.

> Reverse-engineered from the v2.1.2-prod APK. Not affiliated with or
> endorsed by Eldes.

## Features

- **Per-output Open button** – one `button.*` entity per controller output,
  pressing it sends a `POST /devices/{id}/command` and polls the cloud
  for delivery confirmation.
- **Connectivity binary sensor** – `binary_sensor.<gate>_online` reflects
  the controller's `is_alive` flag (cloud-side liveness, not gate
  position — see notes).
- **Diagnostic sensors** – status code, last-updated timestamp, model id.
- **Services**:
  - `eldes_gate.open` – send an open command from automations / scripts.
  - `eldes_gate.refresh` – force a re-poll of the device list.
  - `eldes_gate.forgot_password` – trigger a password-reset email
    (unauthenticated `POST /auth/forgot-password`).
- **Re-auth flow** – if the server rejects the cached credentials, HA
  prompts you for a new password instead of silently failing.
- **Options flow** – tune the polling interval (default 5 min) and the
  open-command confirmation timeout (default 20 s).

## Requirements

- Home Assistant 2024.1.0 or later
- An Eldes Gates account (phone number + password) already provisioned on
  the controller

## Installation

### HACS (recommended)

1. In HACS → Integrations → ⋮ → **Custom repositories**, add
   `https://github.com/bogdan-calapod/ha-eldes-gate` as **Integration**.
2. Install **Eldes Gate** from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Eldes Gate**.

### Manual

1. Copy `custom_components/eldes_gate/` into your HA `config/custom_components/`.
2. Restart Home Assistant.
3. Add the integration through the UI as above.

## Entity layout

For each Eldes device the integration registers an HA **device** with:

| Entity | Type | Notes |
|---|---|---|
| `binary_sensor.<gate>_online` | connectivity | `is_alive` from `GET /devices` |
| `sensor.<gate>_status` | diagnostic | numeric status code |
| `sensor.<gate>_last_updated` | diagnostic (timestamp) | server-reported `updated_at` |
| `sensor.<gate>_model_id` | diagnostic | controller model id |
| `button.<gate>_open_<output_name>` | button | one per output; press to open |

Output buttons take their friendly names from `control_name`, falling
back to `zone_name`, then `Output <n>`.

## Service example

```yaml
service: eldes_gate.open
data:
  device: "Main"       # device id or name
  output: 1            # output number, control_name, or zone_name
  wait: true           # default; set false to fire-and-forget
  timeout: 20          # optional override of the entry option
```

## How it works under the hood

Endpoints exercised (all on `https://ea-gates-api.e-alarms.com`):

| Method | Path | Used for |
|---|---|---|
| `POST` | `/auth/login` | Sign in. Body `{username, password, uuid}`, header `X-App-Version-Code`. Returns `{access_token, expires_at, email}`. |
| `POST` | `/auth/logout` | Drop the session token. |
| `POST` | `/auth/forgot-password` | Request a password-reset email. Body `{email}`. Unauthenticated. |
| `GET`  | `/devices` | Pull every device with its outputs. |
| `POST` | `/devices/{id}/command` | Open: body `{"variables":{"OPN":"<output>;<device_phone>"}}` → `{SEQ, state}`. |
| `GET`  | `/devices/{id}/command/{seq}` | Poll for delivery confirmation. |

The `OPN` value format (`<output_number>;<device_phone>`) was extracted
from the smali of `GatesRepositoryImpl.sendOpen` (`StringBuilder().append(controllerNr).append(';').append(devicePhone)`).
`device_phone` is the SIM phone number on the controller (`DeviceDetail.phone`),
**not** the user's account phone. The string format is a leftover from
the original SMS-based Eldes protocol.

The HTTP client sets `User-Agent: okhttp/4.12.0` because the backend is
fronted by Cloudflare, which blocks generic Python clients with
"error code: 1010" (browser fingerprint). The official app uses OkHttp,
so we match it.

## Caveats

- **No real gate position**. The API tells you the command was
  *delivered* (`confirmed:true`), not whether the physical gate moved.
  This is why outputs are exposed as `button` entities rather than
  `cover` entities.
- **No TLS pinning**. The official app doesn't pin either; we trust the
  system CA store.
- **Account-enumeration in `/auth/forgot-password`**. The server returns
  HTTP 404 `"email not found or not verified"` for unknown addresses
  and a 2xx for known ones. Surfaced as `EldesAPIError` upstream.
- **Cloud-only**. There's no local LAN protocol exposed; every entity
  state depends on cloud polling.

## Development

Reverse-engineering source files (apktool/jadx output, not in this repo):

- `ApiService.java` – Retrofit interface
- `g8/e.java` – Hilt module with the base URL + OkHttp config
- `GatesRepositoryImpl.smali` ~12055–12087 – exact OPN string format
- `LoginResponse.java`, `DeviceDetail.java`, `CommandStatusResponse.java`,
  `DeviceCommandResponse.java`, `ForgotPasswordRequest.java` – JSON shapes

## License

MIT. See [LICENSE](LICENSE).
