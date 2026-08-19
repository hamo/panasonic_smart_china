"""Data update coordinator for Panasonic Smart China devices."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PanasonicApiAuthError, PanasonicApiClient, PanasonicApiError
from .models import PanasonicProfile

_LOGGER = logging.getLogger(__name__)

POLLING_INTERVAL = timedelta(seconds=15)


class PanasonicDeviceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator polling cloud status for a single Panasonic device.

    One coordinator is created per enabled device under an account config
    entry, so all entities of a device share a single polling loop and a
    single cached status dict.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PanasonicApiClient,
        profile: PanasonicProfile,
        usr_id: str,
        device_id: str,
        token: str,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.profile = profile
        self.usr_id = usr_id
        self.device_id = device_id
        self.token = token
        super().__init__(
            hass,
            _LOGGER,
            name=f"panasonic_smart_china_{device_id}",
            update_interval=POLLING_INTERVAL,
        )
        # Link the config entry so DataUpdateCoordinator can auto-trigger a
        # reauth flow when the Panasonic session expires.
        self.config_entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest device status."""
        try:
            return await self.client.get_device_status(
                self.profile, self.usr_id, self.device_id, self.token
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Panasonic Smart China session expired"
            ) from err
        except PanasonicApiError as err:
            raise UpdateFailed(
                f"Fetch status failed for {self.device_id}: {err}"
            ) from err

    async def async_fetch_status(self) -> dict[str, Any] | None:
        """Fetch and cache the latest status outside the poll loop.

        Used by the read-modify-write flow so a command is composed from the
        freshest possible state. Returns None on transient fetch failures.
        """
        try:
            data = await self.client.get_device_status(
                self.profile, self.usr_id, self.device_id, self.token
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Panasonic Smart China session expired"
            ) from err
        except PanasonicApiError as err:
            _LOGGER.debug("Fetch status failed for %s: %s", self.device_id, err)
            return None
        self.async_set_updated_data(data)
        return data

    async def async_send_command(self, params: dict[str, Any]) -> None:
        """Send a control command and optimistically update cached state."""
        try:
            await self.client.set_device_status(
                self.profile, self.usr_id, self.device_id, self.token, params
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Panasonic Smart China session expired"
            ) from err
        except PanasonicApiError as err:
            raise UpdateFailed(f"Set failed for {self.device_id}: {err}") from err

        current = dict(self.data or {})
        current.update(params)
        self.async_set_updated_data(current)
