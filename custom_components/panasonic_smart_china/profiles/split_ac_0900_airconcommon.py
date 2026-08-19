"""Verified profile for Panasonic Smart China 0900 split-type AC devices.

These are the 2024 "AirconCommon" split room units (wall-mounted or
floor-standing, e.g. CS-J9AKT10 / CS-J13AKT10). Unlike the older ducted-AC
profile, the protocol encodes mode and fan-speed enums as single ASCII
character codes, and the runStatus field is inverted ('0' = on, '1' = off).
Temperature still uses a x2 scale.
"""

from __future__ import annotations

from homeassistant.components.climate.const import FAN_AUTO, HVACMode
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfTime

from ..models import (
    BUZZER_BEEP,
    ENTITY_KIND_SPLIT_AC,
    PLATFORM_CLIMATE,
    PROTOCOL_AC_STATUS,
    PanasonicAuxFeature,
    PanasonicEndpoint,
    PanasonicFeature,
    PanasonicProfile,
    PanasonicSelectFeature,
)

FAN_20 = "20%"
FAN_40 = "40%"
FAN_60 = "60%"
FAN_80 = "80%"
FAN_100 = "100%"

# Fields writable via read-modify-write. These are exactly the keys of the
# PARAMS bean the web app (0900/AirconCommon) sends to
# ACDevSetStatusNewProtocol: current values from the device, with only the
# changed field differing. Capability-only fields (nanoe/o2Set/preAirconMode)
# are not in PARAMS and are never sent; all of these keys are returned by the
# device GET, so values written back are always no-ops for unchanged fields.
SAFE_STATUS_KEYS = {
    "buzzer",
    "runStatus",
    "setTemperature",
    "runMode",
    "windSet",
    "portraitWindSet",
    "orientationWindSet",
    "cleanSet",
    "ervWind",
    "ervMode",
    "scene",
    "cool",
    "highCool",
    "elecHeat",
    "lamp",
    "uvc",
    "voiceSet",
    "spaceClean",
}

# runMode is an int code matching the web app's RUN_MODE: 65=auto,
# 66=cool, 67=heat, 68=dry, 69=fan.
HVAC_MAPPING = {
    HVACMode.COOL: 66,
    HVACMode.HEAT: 67,
    HVACMode.DRY: 68,
    HVACMode.AUTO: 65,
    HVACMode.FAN_ONLY: 69,
}

# windSet is an int code: 49='1'(20%), 50='2'(40%), 52='4'(60%), 54='6'(80%),
# 55='7'(100%), 65='A'(auto).
FAN_MAPPING = {
    FAN_AUTO: 65,
    FAN_20: 49,
    FAN_40: 50,
    FAN_60: 52,
    FAN_80: 54,
    FAN_100: 55,
}

# Swing positions match the web app's PORTRAIT_WINDSET / ORIENTATION_WINDSET
# lists (0900/AirconCommon). orientation (left-right) swing is gated by
# leftType; vertical swing is always available. The scene values match the
# web app's SCENE constants (关闭/怡静/超远/环抱).
# Swing positions verified against the App (watched live writes): the
# portrait list is 5 directions 65/68/67/69/66 + auto 70; the orientation
# list is 最左66/偏左108/正对67/偏右87/最右65/自动64.
SELECT_FIELDS = {
    "portrait_swing": PanasonicSelectFeature(
        field="portraitWindSet",
        name="垂直扫风",
        options={
            "方向1": 65, "方向2": 68, "方向3": 67, "方向4": 69, "方向5": 66,
            "自动": 70,
        },
    ),
    "orientation_swing": PanasonicSelectFeature(
        field="orientationWindSet",
        name="水平扫风",
        options={
            "最左": 66,
            "偏左": 108,
            "正对": 67,
            "偏右": 87,
            "最右": 65,
            "自动": 64,
        },
        capability="leftType",
    ),
    "scene": PanasonicSelectFeature(
        field="scene",
        name="场景",
        options={"关闭": 64, "怡静风": 65, "超远风": 66, "环抱风": 67},
    ),
}

# 0/1 feature toggles, gated by the matching "Ex" capability flag. Values
# follow the official App (verified by watching its writes): all are
# 0=OFF/1=ON except lamp, which reports 0=indicator light ON / 1=OFF.
# buzzer has no toggle in the App (sticky read-only 1) and is omitted.
SWITCH_FIELDS = {
    "clean_set": PanasonicFeature("cleanSet", "自清洁", capability="cleanSetEx"),
    "moist_cool": PanasonicFeature("cool", "柔湿制冷", capability="coolEx"),
    "powerful_cool": PanasonicFeature("highCool", "强智冷", capability="highCoolEx"),
    "electric_heat": PanasonicFeature("elecHeat", "辅热", capability="elecHeatEx"),
    "lamp": PanasonicFeature(
        "lamp", "灯光", capability="lampEx", on_value=0, off_value=1
    ),
    "uvc": PanasonicFeature("uvc", "UVC 除菌", capability="uvcEx"),
    "voice": PanasonicFeature("voiceSet", "语音", capability="voiceSetEx"),
    "space_clean": PanasonicFeature("spaceClean", "空间净化", capability="spaceCleanEx"),
}

BINARY_SENSOR_FIELDS = {
    "fresh_air_running": PanasonicFeature(
        "ervMode", "新风运行", equals=66, erv_running=True
    ),
    "alarm": PanasonicFeature("alarmCode", "故障", nonzero=True),
    "filter_due": PanasonicFeature("filterReset", "滤网需更换"),
}

SENSOR_FIELDS = {
    "intake_temperature": PanasonicFeature("inhaleTemperature", "回风温度"),
    "fault_code": PanasonicFeature("alarmCode", "故障码", kind="text"),
}

# Electricity stats from the auxiliary cloud endpoints (60s poll).
# ACGetElectricChargeTodayInfo: {powerToday, durationToday, costToday}
# ACGetElectricChargeDaylyInfo (this month, per day): {powerSelectMonth,
# durationSelectMonth, costSelectMonth, dateList}
# ACGetAirconYearGraphInfo (monthly kWh): {power[12], cost[12], ...}
ELECTRICITY_SENSORS = {
    "energy_today": PanasonicAuxFeature(
        field="powerToday",
        name="今日用电量",
        source="electricity_today",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "duration_today": PanasonicAuxFeature(
        field="durationToday",
        name="今日运行时长",
        source="electricity_today",
        unit=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "cost_today": PanasonicAuxFeature(
        field="costToday",
        name="今日费用",
        source="electricity_today",
        unit="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    "energy_month": PanasonicAuxFeature(
        field="powerSelectMonth",
        name="本月用电量",
        source="electricity_month",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        sum_array=True,
    ),
    "duration_month": PanasonicAuxFeature(
        field="durationSelectMonth",
        name="本月运行时长",
        source="electricity_month",
        unit=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        sum_array=True,
    ),
    "cost_month": PanasonicAuxFeature(
        field="costSelectMonth",
        name="本月费用",
        source="electricity_month",
        unit="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        sum_array=True,
    ),
    "energy_year": PanasonicAuxFeature(
        field="power",
        name="本年用电量",
        source="electricity_year",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        sum_array=True,
    ),
}

# Per-mode temperature memory (ACGetModeTempInfo). Like the official app,
# switching to one of these modes restores the last used temperature.
MODE_TEMP_FIELDS = {
    HVACMode.COOL: "coldModeTemp",
    HVACMode.HEAT: "warmModeTemp",
    HVACMode.DRY: "wetModeTemp",
}

SPLIT_AC_0900_AIRCONCOMMON_PROFILE = PanasonicProfile(
    profile_id="split_ac_0900_airconcommon",
    controller_model="AirconCommon-2024-03",
    name="松下分体空调 (AirconCommon-2024-03)",
    category_ids=frozenset({"0900"}),
    model_ids=frozenset({"AirconCommon-2024-03"}),
    ha_platforms=(
        PLATFORM_CLIMATE,
        "fan",
        "switch",
        "select",
        "binary_sensor",
        "sensor",
        "button",
    ),
    entity_kind=ENTITY_KIND_SPLIT_AC,
    protocol=PROTOCOL_AC_STATUS,
    status_endpoint=PanasonicEndpoint(
        path="ACDevGetStatusInfoAW",
        request_id=100,
        require_results=True,
        required_result_keys=frozenset({"runStatus"}),
    ),
    set_endpoint=PanasonicEndpoint(
        path="ACDevSetStatusNewProtocol",
        request_id=200,
        require_results=False,
    ),
    temp_scale=2,
    default_hvac_mode=HVACMode.COOL,
    hvac_mapping=HVAC_MAPPING,
    fan_mapping=FAN_MAPPING,
    run_status_on_value=48,  # '0'
    run_status_off_value=49,  # '1'
    safe_status_keys=SAFE_STATUS_KEYS,
    command_buzzer=BUZZER_BEEP,  # beep on every command, like the official App
    switch_fields=SWITCH_FIELDS,
    select_fields=SELECT_FIELDS,
    binary_sensor_fields=BINARY_SENSOR_FIELDS,
    sensor_fields=SENSOR_FIELDS,
    electricity_sensors=ELECTRICITY_SENSORS,
    mode_temp_fields=MODE_TEMP_FIELDS,
)
