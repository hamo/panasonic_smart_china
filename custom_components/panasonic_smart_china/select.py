"""Select entities for Panasonic devices, e.g. swing position.

The AirconCommon split units expose two swing controls: portraitWindSet
(vertical, 5 directions + auto) and orientationWindSet (horizontal,
最左/偏左/正对/偏右/最右/自动). Values match the web app's
PORTRAIT_WINDSET and ORIENTATION_WINDSET constants and were verified by
watching the App's live writes.
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import CONF_DEVICES, CONF_ENABLED, DOMAIN
from .helpers import as_int, feature_supported
from .models import PanasonicSelectFeature

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create select entities for enabled devices under an account entry."""
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
        if "select" not in coordinator.profile.ha_platforms:
            continue

        device_name = device_config.get("deviceName", device_id)
        data = coordinator.data or {}
        for key, feature in coordinator.profile.select_fields.items():
            if not feature_supported(data, feature):
                continue
            entities.append(
                PanasonicFeatureSelect(coordinator, device_name, key, feature)
            )

    async_add_entities(entities)


class PanasonicFeatureSelect(CoordinatorEntity, SelectEntity):
    """A selectable status field (swing position) with a label->value map."""

    def __init__(
        self,
        coordinator,
        device_name: str,
        key: str,
        feature: PanasonicSelectFeature,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._feature = feature
        self._attr_name = f"{device_name} {feature.name}"
        self._attr_unique_id = (
            f"panasonic_smart_china_{coordinator.device_id}_{key}"
        )
        self._attr_options = list(feature.options.keys())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=device_name,
            manufacturer="Panasonic",
            model=coordinator.profile.controller_model,
        )

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        value = as_int(data.get(self._feature.field))
        for label, option_value in self._feature.options.items():
            if option_value == value:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        value = self._feature.options.get(option)
        if value is None:
            _LOGGER.warning(
                "Unsupported %s option %s for %s",
                self._feature.name,
                option,
                self.coordinator.device_id,
            )
            return
        try:
            await self.coordinator.async_set_fields({self._feature.field: value})
        except (ConfigEntryAuthFailed, UpdateFailed) as err:
            _LOGGER.error(
                "%s command failed for %s: %s",
                self._feature.name,
                self.coordinator.device_id,
                err,
            )