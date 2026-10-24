"""Constants for the Mitsubishi AC IR integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "mitsubishi_ac_ir"

CONF_BLASTER: Final = "blaster"            # Zigbee2MQTT friendly name
CONF_BASE_TOPIC: Final = "base_topic"
CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"

DEFAULT_NAME: Final = "Mitsubishi AC"
DEFAULT_BASE_TOPIC: Final = "zigbee2mqtt"

# Quick changes within this many seconds are sent as one blast
SEND_DELAY: Final = 1.0

# How long the setup page waits for Zigbee2MQTT's retained device list
BRIDGE_DEVICES_TIMEOUT: Final = 3.0

MIN_TEMP: Final = 16
MAX_TEMP: Final = 31
