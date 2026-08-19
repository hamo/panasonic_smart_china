"""Data update coordinator for Panasonic Smart China devices."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PanasonicApiAuthError, PanasonicApiClient, PanasonicApiError
from .const import (
    ENDPOINT_ELEC_MONTH,
    ENDPOINT_ELEC_TODAY,
    ENDPOINT_ELEC_YEAR,
    ENDPOINT_MODE_TEMP,
)
from .models import PanasonicProfile

_LOGGER = logging.getLogger(__name__)

POLLING_INTERVAL = timedelta(seconds=15)
AUX_POLLING_INTERVAL = timedelta(seconds=60)


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

    async def async_send_command(self, params: dict[str, Any], optimistic: bool = True) -> None:
        """Send a control command and optimistically update cached state."""
        payload = dict(params)
        if self.profile.command_buzzer is not None:
            payload["buzzer"] = self.profile.command_buzzer
        try:
            await self.client.set_device_status(
                self.profile, self.usr_id, self.device_id, self.token, payload
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Panasonic Smart China session expired"
            ) from err
        except PanasonicApiError as err:
            raise UpdateFailed(f"Set failed for {self.device_id}: {err}") from err

        if optimistic:
            current = dict(self.data or {})
            current.update(params)
            self.async_set_updated_data(current)

    async def async_set_fields(self, changes: dict[str, Any]) -> None:
        """Read-modify-write: apply field changes against the latest status."""
        latest = await self.async_fetch_status()
        if not latest:
            raise UpdateFailed(f"Could not fetch status for {self.device_id}")
        merged = dict(latest)
        merged.update(changes)
        safe_keys = self.profile.safe_status_keys
        params = {k: v for k, v in merged.items() if k in safe_keys}
        await self.async_send_command(params)

    async def async_set_field(self, changes: dict[str, Any]) -> None:
        """Send only the given fields, like the App's setStatusInfoAWByOne.

        Some fields only take effect when the payload is partial: the ERV
        (fresh air) starts with a bare ``ervMode`` write but stays dormant
        when the payload also carries ``runStatus``.
        """
        payload = dict(changes)
        if self.profile.command_buzzer is not None:
            payload["buzzer"] = self.profile.command_buzzer
        try:
            await self.client.set_device_status(
                self.profile, self.usr_id, self.device_id, self.token, payload
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed(
                "Panasonic Smart China session expired"
            ) from err
        except PanasonicApiError as err:
            raise UpdateFailed(f"Set failed for {self.device_id}: {err}") from err

        current = dict(self.data or {})
        current.update(changes)
        self.async_set_updated_data(current)


class PanasonicAuxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator polling slow-changing auxiliary endpoints.

    One instance is created per device for profiles that use any of:
    electricity statistics, per-mode temperature memory or the one-shot
    (fix-time) timer. Endpoint failures degrade gracefully: a section is
    simply left out until the next poll succeeds.
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
        """Initialize the auxiliary coordinator."""
        self.client = client
        self.profile = profile
        self.usr_id = usr_id
        self.device_id = device_id
        self.token = token
        super().__init__(
            hass,
            _LOGGER,
            name=f"panasonic_smart_china_aux_{device_id}",
            update_interval=AUX_POLLING_INTERVAL,
        )
        self.config_entry = entry

    def _sections(self) -> list[tuple[str, str, dict[str, Any] | None]]:
        """Return (section, endpoint path, params) tuples for this profile."""
        sections: list[tuple[str, str, dict[str, Any] | None]] = []
        if self.profile.electricity_sensors:
            sections.extend(
                [
                    ("electricity_today", ENDPOINT_ELEC_TODAY, None),
                    (
                        "electricity_month",
                        ENDPOINT_ELEC_MONTH,
                        {"time": time.strftime("%Y%m%d")},
                    ),
                    (
                        "electricity_year",
                        ENDPOINT_ELEC_YEAR,
                        {"time": time.strftime("%Y-%m-%d")},
                    ),
                ]
            )
        if self.profile.mode_temp_fields:
            sections.append(("mode_temp", ENDPOINT_MODE_TEMP, None))
        return sections

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all auxiliary sections, tolerating per-endpoint failures."""
        sections = self._sections()
        results: dict[str, Any] = {}
        failures = 0
        for section, path, params in sections:
            try:
                results[section] = await self.client.get_device_aux(
                    self.profile,
                    self.usr_id,
                    self.device_id,
                    self.token,
                    path,
                    params,
                )
            except PanasonicApiAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Panasonic Smart China session expired"
                ) from err
            except PanasonicApiError as err:
                _LOGGER.debug(
                    "Aux endpoint %s failed for %s: %s",
                    path,
                    self.device_id,
                    err,
                )
                failures += 1
        if failures == len(sections):
            raise UpdateFailed(f"Aux fetch failed for {self.device_id}")
        return results
