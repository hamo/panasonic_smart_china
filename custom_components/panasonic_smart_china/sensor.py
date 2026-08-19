"""Sensors derived from the device status bean and auxiliary endpoints.

Status bean:
- 回风温度 (inhaleTemperature): the intake air temperature measured by the
  unit itself. Uses the same x2 scale as setTemperature; 128 (and any value
  >= 64, i.e. >= 32C at x2) is the "no reading" sentinel reported while the
  unit is off.
- 故障码 (alarmCode): the raw device error code ("0000" = normal), with a
  description attribute for the known codes.

Auxiliary endpoints (60s poll):
- 今日/本月/本年用电量 (electricity totals from ACGetElectricChargeTodayInfo,
  ACGetElectricChargeDaylyInfo and ACGetAirconYearGraphInfo), including run
  duration and cost where the cloud reports them.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICES, CONF_ENABLED, DOMAIN
from .helpers import as_int, feature_supported
from .models import PanasonicAuxFeature, PanasonicFeature

_LOGGER = logging.getLogger(__name__)

_TEMP_SENTINEL_MIN = 64

# Known alarm codes and their meanings (from the official web apps).
ERROR_TEXT = {
    "0000": "正常",
    "OFFLINE": "本体离线",
    "07DF": "碰撞开关不工作，请确认",
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Create sensor entities for enabled devices under an account entry."""
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
        if "sensor" not in coordinator.profile.ha_platforms:
            continue

        device_name = device_config.get("deviceName", device_id)
        data = coordinator.data or {}
        for key, feature in coordinator.profile.sensor_fields.items():
            if not feature_supported(data, feature):
                continue
            entities.append(
                PanasonicFeatureSensor(coordinator, device_name, key, feature)
            )

        aux_coordinator = runtime.get("aux_coordinators", {}).get(device_id)
        if aux_coordinator:
            for key, feature in coordinator.profile.electricity_sensors.items():
                entities.append(
                    PanasonicAuxSensor(aux_coordinator, device_name, key, feature)
                )

    async_add_entities(entities)


class PanasonicFeatureSensor(CoordinatorEntity, SensorEntity):
    """A status field exposed as a HA sensor."""

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
        if feature.field == "inhaleTemperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        if not data:
            return None
        raw = data.get(self._feature.field)
        if raw is None:
            return None
        if self._feature.kind == "text":
            return str(raw)
        raw = as_int(raw)
        if raw is None:
            return None
        if self._feature.field == "inhaleTemperature":
            if raw >= _TEMP_SENTINEL_MIN:
                return None
            return raw / self.coordinator.profile.temp_scale
        return raw

    @property
    def extra_state_attributes(self):
        if self._feature.kind != "text":
            return None
        data = self.coordinator.data or {}
        raw = data.get(self._feature.field)
        description = ERROR_TEXT.get(str(raw)) if raw is not None else None
        if description:
            return {"description": description}
        return None


class PanasonicAuxSensor(CoordinatorEntity, SensorEntity):
    """A sensor derived from an auxiliary endpoint (electricity stats)."""

    def __init__(
        self,
        coordinator,
        device_name: str,
        key: str,
        feature: PanasonicAuxFeature,
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
        if feature.unit:
            self._attr_native_unit_of_measurement = feature.unit
        if feature.device_class:
            self._attr_device_class = feature.device_class
        if feature.state_class:
            self._attr_state_class = feature.state_class

    @property
    def native_value(self) -> float | None:
        data = (self.coordinator.data or {}).get(self._feature.source)
        if not data:
            return None
        raw = data.get(self._feature.field)
        if self._feature.sum_array and isinstance(raw, list):
            total = 0.0
            try:
                for item in raw:
                    total += float(item)
            except (TypeError, ValueError):
                return None
            return round(total, 3)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None