"""Eldes Gate Home Assistant integration."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import (
    EldesAPI,
    EldesAPIError,
    EldesAuthError,
    EldesCommandTimeout,
)
from .const import (
    ATTR_DEVICE,
    ATTR_EMAIL,
    ATTR_OUTPUT,
    ATTR_TIMEOUT,
    ATTR_WAIT,
    CONF_OPEN_TIMEOUT,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_UUID,
    DEFAULT_OPEN_TIMEOUT,
    DOMAIN,
    SERVICE_FORGOT_PASSWORD,
    SERVICE_OPEN,
    SERVICE_REFRESH,
)
from .coordinator import EldesCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

OPEN_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE): cv.string,
        vol.Required(ATTR_OUTPUT): vol.Any(cv.string, vol.Coerce(int)),
        vol.Optional(ATTR_WAIT, default=True): cv.boolean,
        vol.Optional(ATTR_TIMEOUT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=120)
        ),
    }
)

REFRESH_SERVICE_SCHEMA = vol.Schema({})

FORGOT_PASSWORD_SCHEMA = vol.Schema({vol.Required(ATTR_EMAIL): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """No YAML configuration — config flow only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an Eldes Gate config entry."""
    _LOGGER.debug("Setting up Eldes Gate entry %s", entry.entry_id)

    api = EldesAPI(
        phone=entry.data[CONF_PHONE],
        password=entry.data[CONF_PASSWORD],
        uuid=entry.data[CONF_UUID],
    )
    coordinator = EldesCoordinator(hass, entry, api)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await hass.async_add_executor_job(api.close)
        raise
    except Exception as err:
        await hass.async_add_executor_job(api.close)
        # Wrap network / API errors so HA shows the entry as "Failed to set up"
        # and retries with backoff, rather than logging a traceback.
        raise ConfigEntryNotReady(f"Eldes Gate setup failed: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))

    _register_services(hass)

    _LOGGER.debug("Eldes Gate entry %s setup complete", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EldesCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(coordinator.api.close)
        if not hass.data[DOMAIN]:
            for svc in (SERVICE_OPEN, SERVICE_REFRESH, SERVICE_FORGOT_PASSWORD):
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unload_ok


async def _async_reload_on_options_change(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Apply new update interval / open timeout by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_device(coordinator: EldesCoordinator, key: str) -> dict[str, Any] | None:
    """Match a service-call `device` arg to a /devices entry."""
    key_str = str(key).strip()
    devices = coordinator.data.devices
    for d in devices:
        if str(d.get("id")) == key_str:
            return d
    kl = key_str.lower()
    for d in devices:
        if (d.get("name") or "").lower() == kl:
            return d
    return None


def _resolve_output(device: dict[str, Any], key: str | int) -> dict[str, Any] | None:
    ks = str(key).strip()
    try:
        n = int(ks)
    except ValueError:
        n = None
    outputs = device.get("outputs") or []
    if n is not None:
        for o in outputs:
            if int(o.get("number") or -1) == n:
                return o
    kl = ks.lower()
    for o in outputs:
        if (o.get("control_name") or "").lower() == kl:
            return o
        if (o.get("zone_name") or "").lower() == kl:
            return o
    return None


def _register_services(hass: HomeAssistant) -> None:
    """Register services if they aren't already (shared across entries)."""

    async def _async_open(call: ServiceCall) -> None:
        coordinators: list[EldesCoordinator] = list(hass.data[DOMAIN].values())
        if not coordinators:
            _LOGGER.error("eldes_gate.%s: no config entries", SERVICE_OPEN)
            return

        device_key = call.data[ATTR_DEVICE]
        output_key = call.data[ATTR_OUTPUT]
        wait = call.data.get(ATTR_WAIT, True)

        # Search all entries for the device.
        target_coord: EldesCoordinator | None = None
        device: dict[str, Any] | None = None
        for coord in coordinators:
            device = _resolve_device(coord, device_key)
            if device:
                target_coord = coord
                break
        if not device or not target_coord:
            _LOGGER.error(
                "eldes_gate.%s: device %r not found", SERVICE_OPEN, device_key
            )
            return
        output = _resolve_output(device, output_key)
        if not output:
            _LOGGER.error(
                "eldes_gate.%s: output %r not found on device %r",
                SERVICE_OPEN,
                output_key,
                device.get("name"),
            )
            return

        timeout = call.data.get(
            ATTR_TIMEOUT,
            target_coord.entry.options.get(CONF_OPEN_TIMEOUT, DEFAULT_OPEN_TIMEOUT),
        )

        try:
            resp = await hass.async_add_executor_job(
                target_coord.api.send_open,
                device["id"],
                int(output["number"]),
                device.get("phone") or "",
            )
        except EldesAuthError as err:
            _LOGGER.error("Auth error sending open: %s", err)
            target_coord.entry.async_start_reauth(hass)
            return
        except EldesAPIError as err:
            _LOGGER.error("API error sending open: %s", err)
            return

        seq = resp.get("SEQ") or resp.get("seq")
        _LOGGER.info(
            "Eldes open queued: device=%s output=%s SEQ=%s state=%s",
            device.get("name"),
            output.get("number"),
            seq,
            resp.get("state"),
        )
        if wait and seq:
            try:
                await hass.async_add_executor_job(
                    partial(
                        target_coord.api.await_confirmation,
                        device["id"],
                        seq,
                        timeout=float(timeout),
                    ),
                )
            except EldesCommandTimeout as err:
                _LOGGER.warning("%s", err)
            except EldesAPIError as err:
                _LOGGER.error("Error awaiting confirmation: %s", err)

        # Schedule a coordinator refresh so any status changes propagate
        # to entities promptly.
        await target_coord.async_request_refresh()

    async def _async_refresh(call: ServiceCall) -> None:
        for coord in hass.data[DOMAIN].values():
            await coord.async_request_refresh()

    async def _async_forgot_password(call: ServiceCall) -> None:
        # Use any available API instance — the call is unauthenticated.
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            _LOGGER.error(
                "eldes_gate.%s: no entries configured", SERVICE_FORGOT_PASSWORD
            )
            return
        email = call.data[ATTR_EMAIL]
        try:
            result = await hass.async_add_executor_job(
                coord.api.forgot_password, email
            )
        except EldesAPIError as err:
            _LOGGER.error("forgot_password failed: %s", err)
            return
        _LOGGER.info("forgot_password sent for %s: %s", email, result)

    if not hass.services.has_service(DOMAIN, SERVICE_OPEN):
        hass.services.async_register(
            DOMAIN, SERVICE_OPEN, _async_open, schema=OPEN_SERVICE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(
            DOMAIN, SERVICE_REFRESH, _async_refresh, schema=REFRESH_SERVICE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_FORGOT_PASSWORD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORGOT_PASSWORD,
            _async_forgot_password,
            schema=FORGOT_PASSWORD_SCHEMA,
        )
