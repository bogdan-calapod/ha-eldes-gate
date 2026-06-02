"""Button platform — one button per output ('Open <gate>').

Pressing the button sends the open command (POST /devices/{id}/command),
then polls /command/{seq} until confirmed or the entry's open-timeout
elapses.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EldesAPIError, EldesAuthError, EldesCommandTimeout
from .const import (
    ATTRIBUTION,
    CONF_OPEN_TIMEOUT,
    DEFAULT_OPEN_TIMEOUT,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import EldesCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EldesCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[EldesOpenButton] = []
    for device in coordinator.data.devices:
        outputs = device.get("outputs") or []
        # When a controller has a single output, the button name "Open" reads
        # cleanest in the UI ("<Gate name> Open"). With multiple outputs we
        # need the output label to disambiguate ("<Gate> Open Vehicle").
        single_output = len(outputs) == 1
        for output in outputs:
            entities.append(
                EldesOpenButton(
                    coordinator, entry, device, output, single_output
                )
            )
    async_add_entities(entities)
    _LOGGER.info("Created %d Eldes open buttons", len(entities))


def _output_label(output: dict[str, Any]) -> str:
    """Pick the most user-friendly label for an output."""
    return (
        output.get("control_name")
        or output.get("zone_name")
        or f"Output {output.get('number')}"
    )


def _device_info(device: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, str(device.get("id")))},
        name=device.get("name") or f"Eldes {device.get('id')}",
        manufacturer=MANUFACTURER,
        model=str(device.get("model_id") or "Gate Controller"),
        serial_number=device.get("imei"),
        configuration_url="https://eldesalarms.com/",
    )


class EldesOpenButton(CoordinatorEntity[EldesCoordinator], ButtonEntity):
    """One button per output. Pressing sends an open command."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-open"

    def __init__(
        self,
        coordinator: EldesCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
        output: dict[str, Any],
        single_output: bool,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = str(device["id"])
        self._output_number = int(output["number"])
        self._attr_name = "Open" if single_output else f"Open {_output_label(output)}"
        self._attr_unique_id = (
            f"{entry.entry_id}_{self._device_id}_open_{self._output_number}"
        )
        # Translation key + extra attributes make the entity easier to
        # localise and to spot in the entity registry.
        self._attr_translation_key = (
            "open_single" if single_output else "open_output"
        )
        self._attr_translation_placeholders = {
            "output": _output_label(output),
        }

    @property
    def _device(self) -> dict[str, Any]:
        return self.coordinator.data.devices_by_id.get(self._device_id, {})

    @property
    def _output(self) -> dict[str, Any]:
        return (
            self.coordinator.data.output(self._device_id, self._output_number)
            or {}
        )

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self._device)

    @property
    def available(self) -> bool:
        """Available iff the device + output still exist in the latest poll."""
        return bool(self._device) and bool(self._output)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        out = self._output
        dev = self._device
        return {
            "device_id": dev.get("id"),
            "device_name": dev.get("name"),
            "device_phone": dev.get("phone"),
            "output_number": out.get("number"),
            "control_name": out.get("control_name"),
            "zone_name": out.get("zone_name"),
        }

    async def async_press(self) -> None:
        device = self._device
        if not device:
            raise HomeAssistantError(
                f"Eldes device {self._device_id} not found in latest data"
            )
        api = self.coordinator.api
        timeout = float(
            self._entry.options.get(CONF_OPEN_TIMEOUT, DEFAULT_OPEN_TIMEOUT)
        )
        try:
            resp = await self.hass.async_add_executor_job(
                api.send_open,
                device["id"],
                self._output_number,
                device.get("phone") or "",
            )
        except EldesAuthError as err:
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Auth error: {err}") from err
        except EldesAPIError as err:
            raise HomeAssistantError(f"Open command failed: {err}") from err

        seq = resp.get("SEQ") or resp.get("seq")
        _LOGGER.info(
            "Open queued device=%s output=%s SEQ=%s",
            device.get("name"),
            self._output_number,
            seq,
        )
        if seq:
            try:
                await self.hass.async_add_executor_job(
                    partial(
                        api.await_confirmation,
                        device["id"],
                        seq,
                        timeout=timeout,
                    ),
                )
            except EldesCommandTimeout as err:
                # Don't raise — the command may still execute, the
                # confirmation just didn't arrive. Log for diagnostics.
                _LOGGER.warning("Open not confirmed in %ss: %s", timeout, err)
            except EldesAPIError as err:
                _LOGGER.error("Confirmation poll failed: %s", err)

        # Trigger a refresh so any cached status updates land in entities.
        await self.coordinator.async_request_refresh()
