"""Eldes Gates cloud API client.

Reconstructed from the official Android app v2.1.2-prod
(package lt.eldes.smartgate.appswidget). Endpoints exercised:

  POST   /auth/login         body {username, password, uuid}
                             header X-App-Version-Code
                             -> {access_token, expires_at, email, success}
  POST   /auth/logout        header Authorization
  POST   /auth/forgot-password   body {email}
  GET    /devices            header Authorization
                             -> [DeviceDetail...]
  POST   /devices/{id}/command   body {"variables":{"OPN":"<output>;<phone>"}}
                             -> {device_id, SEQ, state}
  GET    /devices/{id}/command/{seq}
                             -> {confirmed, received, ...}

Sync `requests`-based; run via `hass.async_add_executor_job(...)`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .const import (
    API_BASE_URL,
    APP_VERSION_CODE,
    ENDPOINT_DEVICE_COMMAND,
    ENDPOINT_DEVICE_COMMAND_STATUS,
    ENDPOINT_DEVICES,
    ENDPOINT_FORGOT_PASSWORD,
    ENDPOINT_LOGIN,
    ENDPOINT_LOGOUT,
    HTTP_TIMEOUT,
    HTTP_USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class EldesAPIError(Exception):
    """Raised on non-auth API errors (4xx/5xx other than 401/403)."""


class EldesAuthError(EldesAPIError):
    """Raised when credentials are rejected (401/403, or login 4xx)."""


class EldesCommandTimeout(EldesAPIError):
    """Raised when a command was sent but not confirmed in time."""


class EldesAPI:
    """Thin wrapper around the Eldes Gates cloud API.

    Holds a single `requests.Session` and a bearer token. Designed to be
    instantiated per HA config entry and reused across coordinator refreshes
    and service calls.
    """

    def __init__(self, phone: str, password: str, uuid: str) -> None:
        self._phone = phone
        self._password = password
        self._uuid = uuid
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": HTTP_USER_AGENT,
                "Accept": "application/json",
            }
        )
        self._access_token: str | None = None
        self._expires_at: str | None = None
        self._email: str | None = None

    # ------------------------------------------------------------------
    # Credentials / token state
    # ------------------------------------------------------------------

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def expires_at(self) -> str | None:
        return self._expires_at

    @property
    def email(self) -> str | None:
        return self._email

    def update_password(self, password: str) -> None:
        """Replace the stored password (used after a reconfigure flow)."""
        self._password = password
        self._access_token = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self) -> dict[str, Any]:
        """POST /auth/login and cache the bearer token."""
        body = {
            "username": self._phone,
            "password": self._password,
            "uuid": self._uuid,
        }
        url = API_BASE_URL + ENDPOINT_LOGIN
        _LOGGER.debug("Eldes login phone=%s", self._phone)
        try:
            resp = self._session.post(
                url,
                json=body,
                headers={"X-App-Version-Code": APP_VERSION_CODE},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EldesAPIError(f"Network error during login: {exc}") from exc

        if resp.status_code in (401, 403):
            raise EldesAuthError(self._error_message(resp, "invalid credentials"))
        if resp.status_code >= 400:
            raise EldesAuthError(
                f"Login HTTP {resp.status_code}: {self._error_message(resp)}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise EldesAPIError(f"Login returned non-JSON: {exc}") from exc
        token = data.get("access_token")
        if not token:
            raise EldesAuthError("Login response missing access_token")
        self._access_token = token
        self._expires_at = data.get("expires_at")
        self._email = data.get("email")
        return data

    def validate(self) -> bool:
        """Authenticate, raising on failure. Used by the config flow."""
        self.login()
        return True

    def logout(self) -> None:
        """POST /auth/logout. Best-effort; ignores transport errors."""
        if not self._access_token:
            return
        try:
            self._session.post(
                API_BASE_URL + ENDPOINT_LOGOUT,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            _LOGGER.debug("Logout ignored network error: %s", exc)
        finally:
            self._access_token = None
            self._expires_at = None

    # ------------------------------------------------------------------
    # Devices / commands
    # ------------------------------------------------------------------

    def list_devices(self) -> list[dict[str, Any]]:
        """GET /devices. Auto-relogins once on 401/403."""
        return self._authed_json("GET", ENDPOINT_DEVICES)

    def send_open(
        self, device_id: int | str, output_number: int, device_phone: str
    ) -> dict[str, Any]:
        """POST an open command and return the parsed response.

        Body format extracted from
            GatesRepositoryImpl.smali:12055-12087
        which builds OPN as:
            StringBuilder().append(controllerNr).append(';').append(devicePhone)

        Args:
            device_id: numeric device id from /devices
            output_number: 1..N output index ("controllerNr" in the app)
            device_phone: SIM phone number of the controller
                (DeviceDetail.phone), NOT the user's phone
        """
        opn = f"{int(output_number)};{device_phone or ''}"
        body = {"variables": {"OPN": opn}}
        path = ENDPOINT_DEVICE_COMMAND.format(device_id=device_id)
        return self._authed_json("POST", path, json=body)

    def get_command_status(
        self, device_id: int | str, seq: str
    ) -> dict[str, Any]:
        """GET /devices/{id}/command/{seq}."""
        path = ENDPOINT_DEVICE_COMMAND_STATUS.format(
            device_id=device_id, seq=seq
        )
        return self._authed_json("GET", path)

    def await_confirmation(
        self,
        device_id: int | str,
        seq: str,
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        """Poll /command/{seq} until `confirmed:true` or timeout.

        Mirrors CommandConfirmationPoller in the app: exponential backoff
        from 1s up to ~4s, deadline = `timeout` seconds.
        """
        deadline = time.monotonic() + timeout
        interval = 1.0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(interval)
            interval = min(interval * 1.5, 4.0)
            try:
                last = self.get_command_status(device_id, seq)
            except EldesAPIError as exc:
                _LOGGER.debug("Status poll error (will retry): %s", exc)
                continue
            if last.get("confirmed"):
                return last
        raise EldesCommandTimeout(
            f"Command SEQ={seq} on device {device_id} not confirmed within "
            f"{timeout}s (last response: {last})"
        )

    # ------------------------------------------------------------------
    # Password recovery (unauthenticated)
    # ------------------------------------------------------------------

    def forgot_password(self, email: str) -> dict[str, Any]:
        """POST /auth/forgot-password. Body: {email}.

        Note: the server distinguishes "email not found or not verified"
        (HTTP 404) from success, which means this endpoint leaks account
        existence by design. Surfaced upstream as EldesAPIError.
        """
        url = API_BASE_URL + ENDPOINT_FORGOT_PASSWORD
        try:
            resp = self._session.post(
                url,
                json={"email": email},
                headers={"X-App-Version-Code": APP_VERSION_CODE},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EldesAPIError(f"Network error: {exc}") from exc
        if resp.status_code >= 400:
            raise EldesAPIError(
                f"forgot-password HTTP {resp.status_code}: "
                f"{self._error_message(resp)}"
            )
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    # ------------------------------------------------------------------
    # Internal: authenticated request + transparent re-login
    # ------------------------------------------------------------------

    def _authed_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Issue an authenticated request, re-logging in once on 401/403.

        Mirrors GatesRepositoryImpl.authorizedRequestWithRelogin.
        """
        if not self._access_token:
            self.login()
        url = API_BASE_URL + path
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token}"}
            try:
                resp = self._session.request(
                    method, url, json=json, headers=headers, timeout=HTTP_TIMEOUT
                )
            except requests.RequestException as exc:
                raise EldesAPIError(
                    f"Network error on {method} {path}: {exc}"
                ) from exc
            if resp.status_code in (401, 403) and attempt == 1:
                _LOGGER.debug(
                    "Got %s on %s, retrying after relogin", resp.status_code, path
                )
                self._access_token = None
                try:
                    self.login()
                except EldesAuthError:
                    raise
                continue
            if resp.status_code >= 400:
                msg = self._error_message(resp)
                if resp.status_code in (401, 403):
                    raise EldesAuthError(
                        f"{method} {path} HTTP {resp.status_code}: {msg}"
                    )
                raise EldesAPIError(
                    f"{method} {path} HTTP {resp.status_code}: {msg}"
                )
            if resp.status_code == 204 or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError as exc:
                raise EldesAPIError(
                    f"{method} {path} returned non-JSON: {exc}"
                ) from exc
        # Unreachable
        raise EldesAPIError("authed request loop exited unexpectedly")

    @staticmethod
    def _error_message(resp: requests.Response, fallback: str = "") -> str:
        """Try to extract a useful message from an Eldes error envelope."""
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or fallback
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if msg:
                    return str(msg)
            msg = data.get("message")
            if msg:
                return str(msg)
        return resp.text[:300] or fallback
