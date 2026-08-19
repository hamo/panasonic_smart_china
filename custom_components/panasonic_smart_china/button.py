"""Button entities for Panasonic devices.

- 滤网重置 (filter reset): sends the official web app's filter=1 payload to
  ACDevSetStatusNewProtocol to acknowledge a replaced filter. The per-request
  beep (buzzer=65) is injected by the coordinator via the profile's
  command_buzzer, like the App does on every command. The 滤网需更换 binary
  sensor (filterReset field) shows when the unit considers the filter due.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .const import (
    CONF_DEVICES,
    CONF_ENABLED,
    DOMAIN,
    FILTER_RESET_PAYLOAD,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create button entities for enabled devices under an account entry."""
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
        if "filter_due" not in coordinator.profile.binary_sensor_fields:
            continue

        entities.append(
            PanasonicFilterResetButton(
                coordinator,
                device_config.get("deviceName", device_id),
            )
        )

    async_add_entities(entities)


class PanasonicFilterResetButton(CoordinatorEntity, ButtonEntity):
    """Acknowledge a replaced filter so the reminder clears."""

    def __init__(self, coordinator, device_name: str) -> None:
        super().__init__(coordinator)
        self._attr_name = f"{device_name} 滤网重置"
        self._attr_unique_id = (
            f"panasonic_smart_china_{coordinator.device_id}_filter_reset"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=device_name,
            manufacturer="Panasonic",
            model=coordinator.profile.controller_model,
        )

    async def async_press(self) -> None:
        try:
            # No optimistic merge: the beep (buzzer:65) is transient and the
            # filterReset flag only clears after the unit processes it.
            await self.coordinator.async_send_command(
                FILTER_RESET_PAYLOAD, optimistic=False
            )
        except (ConfigEntryAuthFailed, UpdateFailed) as err:
            _LOGGER.error(
                "滤网重置 failed for %s: %s",
                self.coordinator.device_id,
                err,
            )