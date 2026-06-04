"""Constants for the Eldes Gate integration."""

DOMAIN = "eldes_gate"

# ---------------------------------------------------------------------------
# Cloud API
# ---------------------------------------------------------------------------

API_BASE_URL = "https://ea-gates-api.e-alarms.com"

# Mirrors the official Android app v2.1.2-prod. The header is required by
# the /auth/login endpoint; the User-Agent gets us past the Cloudflare WAF
# which rejects generic Python clients with "error code: 1010".
APP_VERSION_CODE = "89737621"
APP_VERSION_NAME = "2.1.2-prod"
HTTP_USER_AGENT = "okhttp/4.12.0"

# Matches the OkHttp client config in the app (GatesRepositoryImpl wiring).
HTTP_TIMEOUT = 15

# Auth
ENDPOINT_LOGIN = "/auth/login"
ENDPOINT_LOGOUT = "/auth/logout"
ENDPOINT_REFRESH = "/auth/refresh"
ENDPOINT_FORGOT_PASSWORD = "/auth/forgot-password"
ENDPOINT_RESET_PASSWORD = "/auth/reset-password"
ENDPOINT_CHANGE_PASSWORD = "/auth/change-password"

# Devices
ENDPOINT_DEVICES = "/devices"
ENDPOINT_DEVICE_COMMAND = "/devices/{device_id}/command"
ENDPOINT_DEVICE_COMMAND_STATUS = "/devices/{device_id}/command/{seq}"


# ---------------------------------------------------------------------------
# Config entry keys
# ---------------------------------------------------------------------------

CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_UUID = "uuid"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_OPEN_TIMEOUT = "open_timeout"

DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes
MIN_UPDATE_INTERVAL = 60
MAX_UPDATE_INTERVAL = 3600

DEFAULT_OPEN_TIMEOUT = 30  # seconds to wait for /command/{seq} confirmation
MIN_OPEN_TIMEOUT = 5
MAX_OPEN_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

SERVICE_OPEN = "open"
SERVICE_REFRESH = "refresh"
SERVICE_FORGOT_PASSWORD = "forgot_password"

ATTR_DEVICE = "device"
ATTR_OUTPUT = "output"
ATTR_WAIT = "wait"
ATTR_TIMEOUT = "timeout"
ATTR_EMAIL = "email"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

ATTRIBUTION = "Data provided by Eldes (ea-gates-api.e-alarms.com)"
MANUFACTURER = "Eldes"
