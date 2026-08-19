"""Feature toggles (0/1 fields) for Panasonic devices, e.g. self-clean,
powerful cool, electric heat, UVC, voice, lamp.

Support is gated by the matching "Ex" capability flag in the status bean,
so entities only appear for features the device actually has.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import CONF_DEVICES, CONF_ENABLED, DOMAIN
from .helpers import as_int, feature_supported
from .models import PanasonicFeature

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create switch entities for enabled devices under an account entry."""
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
        if "switch" not in coordinator.profile.ha_platforms:
            continue

        device_name = device_config.get("deviceName", device_id)
        data = coordinator.data or {}
        for key, feature in coordinator.profile.switch_fields.items():
            if not feature_supported(data, feature):
                continue
            entities.append(
                PanasonicFeatureSwitch(coordinator, device_name, key, feature)
            )

    async_add_entities(entities)


class PanasonicFeatureSwitch(CoordinatorEntity, SwitchEntity):
    """A 0/1 feature toggle backed by read-modify-write field updates."""

    _attr_device_class = SwitchDeviceClass.SWITCH

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

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        if not data:
            return None
        return as_int(data.get(self._feature.field)) == self._feature.on_value

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(self._feature.on_value)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(self._feature.off_value)

    async def _set(self, value: int) -> None:
        try:
            await self.coordinator.async_set_fields({self._feature.field: value})
        except (ConfigEntryAuthFailed, UpdateFailed) as err:
            _LOGGER.error(
                "%s command failed for %s: %s",
                self._feature.name,
                self.coordinator.device_id,
                err,
            )