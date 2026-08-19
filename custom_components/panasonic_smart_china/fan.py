"""Fresh-air (ERV) fan entities for AirconCommon split AC devices."""

from __future__ import annotations

import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import (
    CONF_DEVICES,
    CONF_ENABLED,
    DOMAIN,
    ERV_MODE_OFF,
    ERV_MODE_ON,
    ERV_PRESET_HIGH,
    ERV_PRESET_LOW,
    ERV_PRESET_MEDIUM,
    ERV_TYPE_SUPPORTED,
    ERV_WIND_HIGH,
    ERV_WIND_LOW,
    ERV_WIND_MEDIUM,
)
from .helpers import as_int

_LOGGER = logging.getLogger(__name__)

_ERV_WIND_TO_PRESET = {
    ERV_WIND_LOW: ERV_PRESET_LOW,
    ERV_WIND_MEDIUM: ERV_PRESET_MEDIUM,
    ERV_WIND_HIGH: ERV_PRESET_HIGH,
}

_ERV_PRESET_TO_WIND = {
    ERV_PRESET_LOW: ERV_WIND_LOW,
    ERV_PRESET_MEDIUM: ERV_WIND_MEDIUM,
    ERV_PRESET_HIGH: ERV_WIND_HIGH,
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Create fresh-air fan entities for ERV-capable split AC devices."""
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
        if "fan" not in coordinator.profile.ha_platforms:
            continue
        data = coordinator.data or {}
        if as_int(data.get("ervType")) != ERV_TYPE_SUPPORTED:
            continue

        name = device_config.get("deviceName", device_id)
        entities.append(PanasonicFreshAirEntity(coordinator, name))

    async_add_entities(entities)


class PanasonicFreshAirEntity(CoordinatorEntity, FanEntity):
    """Independent fresh-air (ERV) fan for an AirconCommon split AC."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, device_name: str) -> None:
        super().__init__(coordinator)
        self._attr_name = f"{device_name} 新风"
        self._attr_unique_id = (
            f"panasonic_smart_china_{coordinator.device_id}_fresh_air"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "manufacturer": "Panasonic",
            "model": coordinator.profile.controller_model,
            "name": device_name,
        }
        self._attr_preset_modes = list(_ERV_PRESET_TO_WIND.keys())

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        # The fresh air runs either standalone (ervCheck=1, motor spinning
        # with the AC off) or together with the AC (ervMode=66 while
        # runStatus is on). The cloud keeps the stale ervMode=66 after the
        # AC turns off and the ERV stops with it, so mirror the official
        # App: on = standalone motor running OR AC running with fresh air.
        return as_int(data.get("ervCheck")) == 1 or (
            as_int(data.get("ervMode")) == ERV_MODE_ON
            and as_int(data.get("runStatus"))
            == self.coordinator.profile.run_status_on_value
        )

    @property
    def preset_mode(self) -> str | None:
        data = self.coordinator.data or {}
        return _ERV_WIND_TO_PRESET.get(as_int(data.get("ervWind")))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs,
    ) -> None:
        changes = {"ervMode": ERV_MODE_ON}
        wind = _ERV_PRESET_TO_WIND.get(preset_mode) if preset_mode else None
        if wind is not None:
            changes["ervWind"] = wind
        await self._set_fields(changes)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_fields({"ervMode": ERV_MODE_OFF})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        wind = _ERV_PRESET_TO_WIND.get(preset_mode)
        if wind is None:
            _LOGGER.warning(
                "Unsupported fresh-air level requested: %s", preset_mode
            )
            return
        changes = {"ervWind": wind}
        if not self.is_on:
            changes["ervMode"] = ERV_MODE_ON
        await self._set_fields(changes)

    async def _set_fields(self, changes: dict) -> None:
        """Send a partial payload (only ERV fields).

        A full read-modify-write payload (which carries runStatus) makes the
        device store ervMode without actually starting the fresh air; the
        App writes the ERV fields alone, which is what starts the motor.
        """
        try:
            await self.coordinator.async_set_field(changes)
        except (ConfigEntryAuthFailed, UpdateFailed) as err:
            _LOGGER.error(
                "Fresh-air command failed for %s: %s",
                self.coordinator.device_id,
                err,
            )
