"""Shared device model definitions for Panasonic Smart China."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

PLATFORM_CLIMATE = "climate"

ENTITY_KIND_DUCTED_AC = "ducted_ac"
ENTITY_KIND_SPLIT_AC = "split_ac"
ENTITY_KIND_BATHROOM_HEATER = "bathroom_heater"

PROTOCOL_AC_STATUS = "ac_status"
PROTOCOL_BATHROOM_HEATER = "bathroom_heater"

TOKEN_STRATEGY_DEVICE_ID_SHA512 = "device_id_sha512"

# Per-request beep flag: the official App sets buzzer=65 ('A') on every
# command payload to make the unit beep. It is NOT a persistent setting —
# the status bean's sticky buzzer=1 is the unit's own beep setting, which
# is only echoed back and never sent as a control value.
BUZZER_BEEP = 65


@dataclass(frozen=True)
class PanasonicFeature:
    """A single 0/1 toggle or status field in the device status bean.

    capability is the optional "Ex" flag field (e.g. ``cleanSetEx``) whose
    truthy value gates whether the feature is actually supported.
    kind "text" exposes the raw string value (e.g. the alarm code) instead
    of an integer.
    on_value/off_value let a feature override the standard 0/1 polarity
    (the lamp field reports 0 = indicator light ON, 1 = OFF).
    erv_running marks fresh-air (ERV) running-state features whose value is
    true when the ERV motor spins standalone (ervCheck=1) or when the AC is
    running with fresh air enabled (equals + runStatus), matching the
    official App's display.
    """

    field: str
    name: str
    capability: str | None = None
    nonzero: bool = False
    kind: str = "int"
    on_value: int = 1
    off_value: int = 0
    equals: int | None = None
    erv_running: bool = False


@dataclass(frozen=True)
class PanasonicAuxFeature:
    """A sensor derived from an auxiliary (non-status) endpoint result.

    source names the section of the aux coordinator data (e.g.
    "electricity_today"); field is the key inside that section. sum_array
    marks list fields (month/year arrays) that are summed into a total.
    """

    field: str
    name: str
    source: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    sum_array: bool = False


@dataclass(frozen=True)
class PanasonicSelectFeature:
    """A selectable field (e.g. swing position) with a label->value map."""

    field: str
    name: str
    options: dict[str, int]
    capability: str | None = None


@dataclass(frozen=True)
class PanasonicEndpoint:
    """Description of a Panasonic cloud control endpoint."""

    path: str
    request_id: int
    require_results: bool
    required_result_keys: frozenset[str] = frozenset()
    allow_non_json_response: bool = False


@dataclass(frozen=True)
class PanasonicProfile:
    """Capability and protocol description for a supported device family."""

    profile_id: str
    controller_model: str
    name: str
    category_ids: frozenset[str]
    ha_platforms: tuple[str, ...]
    entity_kind: str
    protocol: str
    status_endpoint: PanasonicEndpoint
    set_endpoint: PanasonicEndpoint
    model_ids: frozenset[str] = frozenset()
    token_strategy: str = TOKEN_STRATEGY_DEVICE_ID_SHA512
    temp_scale: int = 1
    run_status_on_value: int = 1
    run_status_off_value: int = 0
    default_hvac_mode: Any | None = None
    hvac_mapping: dict[Any, int] = field(default_factory=dict)
    fan_mapping: dict[str, int] = field(default_factory=dict)
    fan_payload_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    safe_status_keys: frozenset[str] = frozenset()
    switch_fields: dict[str, PanasonicFeature] = field(default_factory=dict)
    select_fields: dict[str, PanasonicSelectFeature] = field(default_factory=dict)
    sensor_fields: dict[str, PanasonicFeature] = field(default_factory=dict)
    binary_sensor_fields: dict[str, PanasonicFeature] = field(default_factory=dict)
    electricity_sensors: dict[str, PanasonicAuxFeature] = field(default_factory=dict)
    mode_temp_fields: dict[Any, str] = field(default_factory=dict)
    cookie_required: bool = False
    referer_template: str | None = None
    extra_control_headers: dict[str, str] = field(default_factory=dict)
    # Per-request beep flag added to every control payload (e.g. 65 for the
    # AirconCommon split units). Not a persistent state field.
    command_buzzer: int | None = None

    def matches_category(self, category_id: str | None) -> bool:
        """Return whether this profile supports a Panasonic category id."""
        return bool(category_id and category_id in self.category_ids)

    def matches_device(
        self,
        category_id: str | None,
        model_values: set[str] | frozenset[str] | None = None,
    ) -> bool:
        """Return whether this profile supports a concrete cloud device."""
        if not self.matches_category(category_id):
            return False
        if not self.model_ids:
            return True
        normalized_models = {
            value.strip().upper()
            for value in (model_values or set())
            if value and value.strip()
        }
        supported_models = {value.upper() for value in self.model_ids}
        return bool(normalized_models & supported_models)
