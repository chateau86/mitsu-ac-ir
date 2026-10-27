"""Constants for the Mitsubishi AC IR integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "mitsubishi_ac_ir"

CONF_BLASTER: Final = "blaster"            # Zigbee2MQTT friendly name
CONF_BASE_TOPIC: Final = "base_topic"
CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"
# HA-side only: sent setting = HA target + offset. For a unit that holds the
# room 2 °C below what it's set to, use +2. The encoder never sees it.
CONF_TEMPERATURE_OFFSET: Final = "temperature_offset"

DEFAULT_NAME: Final = "Mitsubishi AC"
DEFAULT_BASE_TOPIC: Final = "zigbee2mqtt"

# Quick changes within this many seconds are sent as one blast
SEND_DELAY: Final = 1.0

# How long the setup page waits for Zigbee2MQTT's retained device list
BRIDGE_DEVICES_TIMEOUT: Final = 3.0

# What the unit accepts. HA's own range is this minus the offset.
MIN_TEMP: Final = 16
MAX_TEMP: Final = 31

DEFAULT_TEMPERATURE_OFFSET: Final = 0
MAX_TEMPERATURE_OFFSET: Final = 10      # allowed range is +-this
