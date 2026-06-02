"""Config flow for the Eldes Gate integration."""

from __future__ import annotations

import logging
import uuid as uuid_mod
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import EldesAPI, EldesAPIError, EldesAuthError
from .const import (
    CONF_OPEN_TIMEOUT,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_UPDATE_INTERVAL,
    CONF_UUID,
    DEFAULT_OPEN_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_OPEN_TIMEOUT,
    MAX_UPDATE_INTERVAL,
    MIN_OPEN_TIMEOUT,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_credentials(
    hass: HomeAssistant, phone: str, password: str, uuid_value: str
) -> str | None:
    """Try to log in. Return None on success or an error key string."""
    api = EldesAPI(phone, password, uuid_value)
    try:
        await hass.async_add_executor_job(api.validate)
    except EldesAuthError:
        return "invalid_auth"
    except EldesAPIError:
        return "cannot_connect"
    except Exception:  # pragma: no cover
        _LOGGER.exception("Unexpected error validating Eldes credentials")
        return "unknown"
    finally:
        await hass.async_add_executor_job(api.close)
    return None


class EldesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup flow: phone + password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()
            password = user_input[CONF_PASSWORD]
            # The Eldes API enforces a single-bound-UUID policy per account:
            # every fresh login from a different UUID gets back 401
            # "this account registered on a different device".
            #
            # By default we mint a new UUID. The user can paste the phone
            # app's UUID instead to coexist with the mobile app (both look
            # like the same device to the server). See README for how to
            # extract `vendorid` from the app's SharedPreferences.
            raw_uuid = (user_input.get(CONF_UUID) or "").strip()
            uuid_value = raw_uuid or str(uuid_mod.uuid4())

            await self.async_set_unique_id(phone.lower())
            self._abort_if_unique_id_configured()

            error = await _validate_credentials(
                self.hass, phone, password, uuid_value
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Eldes ({phone})",
                    data={
                        CONF_PHONE: phone,
                        CONF_PASSWORD: password,
                        CONF_UUID: uuid_value,
                    },
                    options={
                        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                        CONF_OPEN_TIMEOUT: DEFAULT_OPEN_TIMEOUT,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PHONE): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_UUID, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "uuid_hint": (
                    "Leave blank to mint a new device UUID (will kick the "
                    "Eldes mobile app off this account the next time it "
                    "re-logs in). Paste the phone's UUID to share the slot."
                ),
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Triggered by the API client when credentials are no longer valid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry_id = self.context.get("entry_id")
        entry = (
            self.hass.config_entries.async_get_entry(entry_id)
            if entry_id
            else None
        )

        if user_input is not None and entry is not None:
            password = user_input[CONF_PASSWORD]
            error = await _validate_credentials(
                self.hass,
                entry.data[CONF_PHONE],
                password,
                entry.data[CONF_UUID],
            )
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_PASSWORD: password},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EldesOptionsFlow:
        return EldesOptionsFlow(config_entry)


class EldesOptionsFlow(config_entries.OptionsFlow):
    """Edit update interval and open-command timeout."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_timeout = self.config_entry.options.get(
            CONF_OPEN_TIMEOUT, DEFAULT_OPEN_TIMEOUT
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
                vol.Optional(
                    CONF_OPEN_TIMEOUT, default=current_timeout
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_OPEN_TIMEOUT, max=MAX_OPEN_TIMEOUT),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
