import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import PanasonicApiClient
from .const import (
    CONF_CATEGORY,
    CONF_CONTROLLER_MODEL,
    CONF_DEVICES,
    CONF_ENABLED,
    CONF_PROFILE_ID,
    CONF_SSID,
    CONF_TOKEN,
    CONF_USR_ID,
    DOMAIN,
)
from .coordinator import PanasonicDeviceCoordinator
from .profiles import find_profile_for_device_config, supported_platforms

_LOGGER = logging.getLogger(__name__)

PLATFORMS = list(supported_platforms())


async def async_setup(hass: HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})
    client = PanasonicApiClient(hass, entry.data.get(CONF_SSID))
    coordinators = _build_coordinators(hass, entry, client)

    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinators": coordinators,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _build_coordinators(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: PanasonicApiClient,
) -> dict[str, PanasonicDeviceCoordinator]:
    """Create one coordinator per enabled device under the account entry."""
    coordinators = {}
    devices = entry.data.get(CONF_DEVICES, {})

    for device_id, device_config in devices.items():
        if not device_config.get(CONF_ENABLED, True):
            continue

        profile = find_profile_for_device_config(
            profile_id=device_config.get(CONF_PROFILE_ID),
            controller_model=device_config.get(CONF_CONTROLLER_MODEL),
            category_id=device_config.get(CONF_CATEGORY),
        )
        if not profile:
            _LOGGER.error("Device profile not found for %s.", device_id)
            continue

        coordinators[device_id] = PanasonicDeviceCoordinator(
            hass,
            entry,
            client,
            profile,
            entry.data.get(CONF_USR_ID),
            device_id,
            device_config.get(CONF_TOKEN),
        )

    return coordinators
