"""Per-unit state, persistence, debounce and MQTT publish."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_TOPIC,
    CONF_BLASTER,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_BASE_TOPIC,
    DOMAIN,
    SEND_DELAY,
)
from .protocol import AcState, Fan, Mode, Vane, encode

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# The settings HA controls; everything else in AcState stays at its default
_STORED_FIELDS = ("power", "mode", "temperature", "fan", "vane", "clean", "eco", "turbo")
_ENUMS = {"mode": Mode, "fan": Fan, "vane": Vane}

type MitsubishiConfigEntry = ConfigEntry[AcController]


class AcController:
    """One AC unit: its assumed state, shared by the climate and switch entities.

    IR is one-way, so the state is what we last sent. It's saved to HA's
    storage so it survives restarts, and nothing is sent at startup.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.state = AcState()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[Callable[[], None]] = []
        self._cancel_send: CALLBACK_TYPE | None = None

    @property
    def config(self) -> dict[str, Any]:
        """Entry settings, with options (from the Configure page) taking priority."""
        return {**self.entry.data, **self.entry.options}

    @property
    def topic(self) -> str:
        base = self.config.get(CONF_BASE_TOPIC) or DEFAULT_BASE_TOPIC
        return f"{base}/{self.config[CONF_BLASTER]}/set/ir_code_to_send"

    @property
    def temperature_sensor(self) -> str | None:
        return self.config.get(CONF_TEMPERATURE_SENSOR) or None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Mitsubishi Electric",
            model="Split AC (IR)",
        )

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return
        values = {}
        for key in _STORED_FIELDS:
            if key in stored:
                value = stored[key]
                values[key] = _ENUMS[key](value) if key in _ENUMS else value
        try:
            self.state = replace(self.state, **values)
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring unreadable saved state for %s", self.entry.title)

    @callback
    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call listener whenever the state changes. Returns a remover."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def update(self, **changes: Any) -> None:
        """Change settings, refresh the entities, and schedule a blast."""
        self.state = replace(self.state, **changes)
        for listener in list(self._listeners):
            listener()
        self._store.async_delay_save(self._data_to_save, SEND_DELAY)
        # Debounce: restart the timer, so quick changes go out as one blast
        if self._cancel_send:
            self._cancel_send()
        self._cancel_send = async_call_later(self.hass, SEND_DELAY, self._send_later)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {key: int(v) if key in _ENUMS else v
                for key in _STORED_FIELDS
                for v in [getattr(self.state, key)]}

    @callback
    def _send_later(self, _now: Any) -> None:
        self._cancel_send = None
        self.entry.async_create_background_task(
            self.hass, self.async_send(), f"{DOMAIN} send"
        )

    async def async_send(self) -> None:
        """Encode the full state with the current time and publish it."""
        state = replace(self.state, clock=dt_util.now().time())
        # The compressor is pure Python; keep it off the event loop
        code = await self.hass.async_add_executor_job(encode, state)
        _LOGGER.debug("Sending %s to %s", state, self.topic)
        await mqtt.async_publish(self.hass, self.topic, code, qos=0, retain=False)

    @callback
    def async_shutdown(self) -> None:
        """Drop a pending blast when the entry unloads."""
        if self._cancel_send:
            self._cancel_send()
            self._cancel_send = None
