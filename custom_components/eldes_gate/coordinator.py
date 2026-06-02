"""Data update coordinator for Eldes Gate."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import EldesAPI, EldesAPIError, EldesAuthError
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EldesData:
    """Single refresh result, indexed for O(1) entity lookups."""

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.devices = devices
        self.devices_by_id: dict[str, dict[str, Any]] = {
            str(d["id"]): d for d in devices if "id" in d
        }

    def output(self, device_id: str, output_number: int) -> dict[str, Any] | None:
        device = self.devices_by_id.get(str(device_id))
        if not device:
            return None
        for o in device.get("outputs") or []:
            if int(o.get("number") or -1) == int(output_number):
                return o
        return None


class EldesCoordinator(DataUpdateCoordinator[EldesData]):
    """Polls GET /devices on a configurable interval."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: EldesAPI
    ) -> None:
        self.api = api
        self.entry = entry
        update_interval = entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> EldesData:
        try:
            devices = await self.hass.async_add_executor_job(self.api.list_devices)
        except EldesAuthError as err:
            raise UpdateFailed(f"Auth error: {err}") from err
        except EldesAPIError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.exception("Unexpected error fetching Eldes devices")
            raise UpdateFailed(f"Unexpected error: {err}") from err
        if not isinstance(devices, list):
            raise UpdateFailed(f"/devices returned non-list: {type(devices)!r}")
        return EldesData(devices=devices)
