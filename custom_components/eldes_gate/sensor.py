"""Sensor platform — status code and last-updated timestamp."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import EldesCoordinator

_LOGGER = logging.getLogger(__name__)


SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="status",
        translation_key="status",
        name="Status",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="updated_at",
        translation_key="updated_at",
        name="Last Updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="model_id",
        translation_key="model_id",
        name="Model ID",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EldesCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for device in coordinator.data.devices:
        device_id = device.get("id")
        if device_id is None:
            continue
        for desc in SENSOR_DESCRIPTIONS:
            entities.append(
                EldesDeviceSensor(coordinator, entry, str(device_id), desc)
            )
    async_add_entities(entities)
    _LOGGER.info("Created %d Eldes sensors", len(entities))


class EldesDeviceSensor(CoordinatorEntity[EldesCoordinator], SensorEntity):
    """Per-device diagnostic sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EldesCoordinator,
        entry: ConfigEntry,
        device_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self.entity_description = description
        self._attr_unique_id = (
            f"{entry.entry_id}_{device_id}_{description.key}"
        )

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
    def native_value(self) -> Any:
        key = self.entity_description.key
        value = self._device.get(key)
        if value is None:
            return None
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            if isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    _LOGGER.debug("Bad timestamp %s=%r", key, value)
                    return None
        return value
