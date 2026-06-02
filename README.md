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

## Dashboards

Once the integration is added, every gate appears as an HA **device** with
its own buttons, sensors and connectivity binary sensor. You can drop any
of them on a dashboard with the regular UI editor (**Edit dashboard →
Add card → pick an entity**). A few patterns that work well:

### Tile card per gate (recommended)

```yaml
type: tile
entity: button.bariera_c8_open       # single-output device
name: Bariera C8
icon: mdi:boom-gate
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.bariera_c8_open
```

For a multi-output device (one button per output):

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: binary_sensor.poarta_pietonala_c8_online
    name: Poarta Pietonala C8
    icon: mdi:gate
  - type: horizontal-stack
    cards:
      - type: tile
        entity: button.poarta_pietonala_c8_open_poarta_c8
        name: Pedestrian
        icon: mdi:walk
        tap_action: { action: perform-action, perform_action: button.press,
                      target: { entity_id: button.poarta_pietonala_c8_open_poarta_c8 } }
```

### Classic button card

```yaml
type: button
entity: button.bariera_c8_open
name: Open Barrier
icon: mdi:boom-gate-up
show_state: false
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.bariera_c8_open
```

### Entities card grouping a device

```yaml
type: entities
title: Bariera C8
entities:
  - entity: binary_sensor.bariera_c8_online
  - entity: sensor.bariera_c8_status
  - entity: sensor.bariera_c8_last_updated
  - type: button
    name: Open
    icon: mdi:boom-gate-up
    action_name: OPEN
    tap_action:
      action: perform-action
      perform_action: button.press
      target:
        entity_id: button.bariera_c8_open
```

### Calling the service directly (scripts / automations / shortcuts)

```yaml
script:
  open_bariera_c8:
    alias: Open Bariera C8
    sequence:
      - service: eldes_gate.open
        data:
          device: "Bariera C8"
          output: 1
          wait: true
          timeout: 20
```

This is also what you'd point the iOS / Android Home Assistant
companion-app widgets at if you want a one-tap open shortcut on your
phone home screen.

### Entity naming convention

With `has_entity_name=True`, HA prefixes the device name automatically.
So a controller named "Bariera C8" with a single output gives you:

| Entity ID | Friendly name |
|---|---|
| `button.bariera_c8_open` | Bariera C8 Open |
| `binary_sensor.bariera_c8_online` | Bariera C8 Online |
| `sensor.bariera_c8_status` | Bariera C8 Status |
| `sensor.bariera_c8_last_updated` | Bariera C8 Last updated |
| `sensor.bariera_c8_model_id` | Bariera C8 Model ID |

Controllers with multiple outputs get one `button.*_open_<output>` per
output, e.g. `button.<gate>_open_pedestrian`, `button.<gate>_open_vehicle`.

Status / Last updated / Model ID are tagged as **diagnostic** entities,
so they sit under the "Diagnostic" section of the device page (still
addable to dashboards if you want them there).

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

## Single-device UUID lock (important)

The Eldes cloud API enforces **one device UUID per account at a time**:

```
empty UUID      → 400 "username, password and uuid are required"
new UUID        → 401 "this account registered on a different device"
the bound UUID  → 200 OK
```

The official mobile app sidesteps this by generating one UUID on first
install (stored as `vendorid` in its `SharedPreferences`) and reusing
it forever. As soon as a second client logs in with a different UUID,
the server rebinds and the previous client gets the 401 on its next
attempt.

For HA this means **two realistic setups**:

1. **HA-only.** Leave the "Device UUID" field in the config flow empty.
   The integration mints a fresh UUID and binds the account to itself.
   The phone app will sign out the next time it tries to talk to the
   server. (You can still re-log in on the phone later, but that will
   then kick HA out — tug-of-war.)
2. **HA + phone sharing the same UUID.** Paste the phone's `vendorid`
   into the "Device UUID" field. Both clients then look identical to
   the server's UUID check, so neither kicks the other on login. They
   each still get their own bearer token.

### Extracting the phone's UUID

On a **rooted Android** device:

```sh
adb shell su -c \
  'cat /data/data/lt.eldes.smartgate.appswidget/shared_prefs/lt.eldes.smargate.appswidget.xml' \
  | grep vendorid
```

> Note the SharedPreferences filename has a typo — `smargate`, not
> `smartgate`. It's a quirk in the app itself.

You'll get a line like:

```xml
<string name="vendorid">a1b2c3d4-e5f6-7890-abcd-ef1234567890</string>
```

Paste that UUID into the integration's setup form.

On a **non-rooted** device the cleanest path is `adb backup` of the
package, unpacking the tar inside, and grepping the same file. Some
Android versions disable backup for this app — in that case there's no
non-root way to extract it and you're stuck with option 1.

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
