"""Setup page (one entry per AC unit) and Configure page."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    BRIDGE_DEVICES_TIMEOUT,
    CONF_BASE_TOPIC,
    CONF_BLASTER,
    CONF_TEMPERATURE_OFFSET,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_BASE_TOPIC,
    DEFAULT_NAME,
    DEFAULT_TEMPERATURE_OFFSET,
    DOMAIN,
    MAX_TEMPERATURE_OFFSET,
)

_LOGGER = logging.getLogger(__name__)


def _has_ir_send(node: Any) -> bool:
    """True if a Zigbee2MQTT exposes tree contains ir_code_to_send."""
    if isinstance(node, dict):
        if node.get("property") == "ir_code_to_send":
            return True
        return any(_has_ir_send(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_ir_send(v) for v in node)
    return False


async def _async_list_blasters(hass: HomeAssistant, base_topic: str) -> list[str]:
    """Friendly names of Zigbee2MQTT devices that can send IR codes.

    Reads the retained <base>/bridge/devices message. Returns [] if MQTT or
    Zigbee2MQTT doesn't answer in time; the form then takes typed names.
    """
    if not await mqtt.async_wait_for_mqtt_client(hass):
        return []
    received = asyncio.Event()
    names: list[str] = []

    @callback
    def _on_devices(msg: mqtt.ReceiveMessage) -> None:
        try:
            devices = json.loads(msg.payload)
        except ValueError:
            return
        names[:] = sorted(
            d["friendly_name"]
            for d in devices
            if isinstance(d, dict) and "friendly_name" in d and _has_ir_send(d.get("definition"))
        )
        received.set()

    unsubscribe = await mqtt.async_subscribe(hass, f"{base_topic}/bridge/devices", _on_devices)
    try:
        await asyncio.wait_for(received.wait(), BRIDGE_DEVICES_TIMEOUT)
    except TimeoutError:
        _LOGGER.debug("No device list on %s/bridge/devices", base_topic)
    finally:
        unsubscribe()
    return names


def _schema(blasters: list[str], defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = str
    fields[vol.Required(CONF_BLASTER, default=defaults.get(CONF_BLASTER, vol.UNDEFINED))] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=blasters,
                custom_value=True,       # type a name if the list is empty or wrong
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    )
    fields[vol.Required(
        CONF_BASE_TOPIC, default=defaults.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
    )] = str
    fields[vol.Optional(
        CONF_TEMPERATURE_SENSOR,
        description={"suggested_value": defaults.get(CONF_TEMPERATURE_SENSOR)},
    )] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
    )
    fields[vol.Required(
        CONF_TEMPERATURE_OFFSET,
        default=defaults.get(CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET),
    )] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=-MAX_TEMPERATURE_OFFSET,
            max=MAX_TEMPERATURE_OFFSET,
            step=1,
            unit_of_measurement="°C",
            mode=selector.NumberSelectorMode.BOX,
        )
    )
    return vol.Schema(fields)


class MitsubishiAcIrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one AC unit."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            blaster = user_input[CONF_BLASTER].strip()
            if not blaster:
                errors[CONF_BLASTER] = "blaster_required"
            else:
                # One entry per blaster: each unit has its own
                await self.async_set_unique_id(blaster)
                self._abort_if_unique_id_configured()
                data = {
                    **user_input,
                    CONF_BLASTER: blaster,
                    # NumberSelector gives a float
                    CONF_TEMPERATURE_OFFSET: int(user_input.get(CONF_TEMPERATURE_OFFSET, 0)),
                }
                return self.async_create_entry(title=data.pop(CONF_NAME), data=data)

        blasters = await _async_list_blasters(self.hass, DEFAULT_BASE_TOPIC)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(blasters, user_input or {}, with_name=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MitsubishiAcIrOptionsFlow()


class MitsubishiAcIrOptionsFlow(OptionsFlow):
    """Change a unit's blaster, base topic or sensor without removing it."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            blaster = user_input[CONF_BLASTER].strip()
            if not blaster:
                errors[CONF_BLASTER] = "blaster_required"
            else:
                return self.async_create_entry(data={
                    **user_input,
                    CONF_BLASTER: blaster,
                    # Store None when cleared, so it overrides the setup value
                    CONF_TEMPERATURE_SENSOR: user_input.get(CONF_TEMPERATURE_SENSOR),
                    CONF_TEMPERATURE_OFFSET: int(user_input.get(CONF_TEMPERATURE_OFFSET, 0)),
                })

        base = current.get(CONF_BASE_TOPIC) or DEFAULT_BASE_TOPIC
        blasters = await _async_list_blasters(self.hass, base)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(blasters, current, with_name=False),
            errors=errors,
        )
