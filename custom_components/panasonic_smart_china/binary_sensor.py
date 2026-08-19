"""Binary sensors derived from the device status bean.

- 新风运行: the fresh-air (ERV) unit is running (standalone motor spinning
  or the AC running with fresh air enabled), matching the official App.
- 故障 (alarmCode): non-zero error code reported by the device.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICES, CONF_ENABLED, DOMAIN
from .helpers import as_int, feature_supported
from .models import PanasonicFeature

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create binary sensor entities for enabled devices under an account entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = runtime.get("coordinators", {})
    devices = entry.data.get(CONF_DEVICES, {})

    entities = []
    for device_id, device_config in devices.items():
        if not device_config.get(CONF_ENABLED, True):
            continue
        coordinator = coordinators.get(device_id)
        if not coordinator:
            continue
        if "binary_sensor" not in coordinator.profile.ha_platforms:
            continue

        device_name = device_config.get("deviceName", device_id)
        data = coordinator.data or {}
        for key, feature in coordinator.profile.binary_sensor_fields.items():
            if not feature_supported(data, feature):
                continue
            entities.append(
                PanasonicFeatureBinarySensor(
                    coordinator, device_name, key, feature
                )
            )

    async_add_entities(entities)


class PanasonicFeatureBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """A status flag from the device bean (0/1 or non-zero semantics)."""

    def __init__(
        self,
        coordinator,
        device_name: str,
        key: str,
        feature: PanasonicFeature,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._feature = feature
        self._attr_name = f"{device_name} {feature.name}"
        self._attr_unique_id = (
            f"panasonic_smart_china_{coordinator.device_id}_{key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=device_name,
            manufacturer="Panasonic",
            model=coordinator.profile.controller_model,
        )
        if feature.field == "alarmCode":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif feature.equals is not None:
            self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        if not data:
            return None
        if self._feature.erv_running:
            # Fresh-air running: standalone ERV motor spinning (ervCheck=1)
            # or AC running with fresh air enabled (equals + runStatus on).
            # The cloud keeps the stale setting after the AC turns off and
            # the ERV stops with it, so mirror the official App.
            return as_int(data.get("ervCheck")) == 1 or (
                as_int(data.get(self._feature.field)) == self._feature.equals
                and as_int(data.get("runStatus"))
                == self.coordinator.profile.run_status_on_value
            )
        value = data.get(self._feature.field)
        if self._feature.equals is not None:
            return as_int(value) == self._feature.equals
        if self._feature.nonzero:
            return value not in (0, "0", "0000", "", None)
        return as_int(value) == 1