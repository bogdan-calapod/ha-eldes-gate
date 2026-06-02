"""Binary sensor — controller connectivity (`is_alive`)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import EldesCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EldesCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        EldesAliveBinarySensor(coordinator, entry, str(device["id"]))
        for device in coordinator.data.devices
        if "id" in device
    ]
    async_add_entities(entities)
    _LOGGER.info("Created %d Eldes connectivity sensors", len(entities))


class EldesAliveBinarySensor(
    CoordinatorEntity[EldesCoordinator], BinarySensorEntity
):
    """ON when the controller's `is_alive` flag is true."""

    _attr_attribution = ATTRIBUTION
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Online"

    def __init__(
        self,
        coordinator: EldesCoordinator,
        entry: ConfigEntry,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_alive"

    @property
    def _device(self) -> dict[str, Any]:
        return self.coordinator.data.devices_by_id.get(self._device_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        d = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=d.get("name") or f"Eldes {self._device_id}",
            manufacturer=MANUFACTURER,
            model=str(d.get("model_id") or "Gate Controller"),
            serial_number=d.get("imei"),
            configuration_url="https://eldesalarms.com/",
        )

    @property
    def available(self) -> bool:
        return bool(self._device)

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if "is_alive" not in device:
            return None
        return bool(device.get("is_alive"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        return {
            "device_id": d.get("id"),
            "imei": d.get("imei"),
            "phone": d.get("phone"),
            "model_id": d.get("model_id"),
            "status": d.get("status"),
            "updated_at": d.get("updated_at"),
        }
