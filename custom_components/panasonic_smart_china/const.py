from homeassistant.const import (
    CONF_DEVICES,
    CONF_ENABLED,
    CONF_TOKEN,
    CONF_USERNAME,
)

from .profiles import (
    find_profiles_for_category,
    find_profiles_for_device,
)
from .profiles.ducted_ac_0900 import FAN_MUTE

DOMAIN = "panasonic_smart_china"

CONF_USR_ID = "usrId"
CONF_DEVICE_ID = "deviceId"
CONF_SSID = "SSID"
CONF_SENSOR_ID = "sensor_entity_id"
CONF_CONTROLLER_MODEL = "controller_model"
CONF_FAMILY_ID = "familyId"
CONF_REAL_FAMILY_ID = "realFamilyId"
CONF_DEVICE_NAME = "deviceName"
CONF_DEVICE_MODEL = "device_model"
CONF_CATEGORY = "category"
CONF_PROFILE_ID = "profile_id"
CONF_HA_PLATFORMS = "ha_platforms"
CONF_ENTITY_KIND = "entity_kind"

# AirconCommon split-AC fresh-air (ERV) protocol values.
ERV_MODE_ON = 66  # 'B'
ERV_MODE_OFF = 64  # '@'
ERV_TYPE_SUPPORTED = 1
ERV_WIND_LOW = 1
ERV_WIND_MEDIUM = 2
ERV_WIND_HIGH = 3
ERV_PRESET_LOW = "low"
ERV_PRESET_MEDIUM = "medium"
ERV_PRESET_HIGH = "high"

# Auxiliary read-only endpoints used by the AirconCommon split web app.
ENDPOINT_ELEC_TODAY = "ACGetElectricChargeTodayInfo"
ENDPOINT_ELEC_MONTH = "ACGetElectricChargeDaylyInfo"
ENDPOINT_ELEC_YEAR = "ACGetAirconYearGraphInfo"
ENDPOINT_MODE_TEMP = "ACGetModeTempInfo"

# Filter reset payload values from the official web app (FILTER.ON=1).
# The per-request beep (buzzer=65) is injected by the coordinator via the
# profile's command_buzzer, like the App does on every command.
FILTER_RESET_PAYLOAD = {"filter": 1}


def find_controllers_for_category(category_id):
    """根据设备 ID 中的 category_id 查找匹配的控制器列表"""
    profiles = find_profiles_for_category(category_id)
    return {
        profile.controller_model: profile
        for profile in profiles.values()
    }


def find_controllers_for_device(category_id, model_values=None):
    """根据 category_id 和设备型号候选值查找匹配的控制器列表"""
    profiles = find_profiles_for_device(category_id, model_values)
    return {
        profile.controller_model: profile
        for profile in profiles.values()
    }


def extract_category_from_device_id(device_id):
    """从 deviceId (格式: MAC_CATEGORY_SUFFIX) 中提取 category_id"""
    parts = device_id.split('_', 2)
    if len(parts) >= 2:
        return parts[1]
    return None
