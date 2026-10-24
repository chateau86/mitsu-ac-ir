"""Turbo, Eco and Clean switches for one AC unit (open-loop, like the climate entity)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import AcController, MitsubishiConfigEntry

# (AcState field, translation key, icon, turning it on also turns the AC on)
# Clean doesn't power on: the remote treats it as a persistent setting, so
# while the AC is off it just waits for the next command.
SWITCHES = (
    ("turbo", "turbo", "mdi:fan-plus", True),
    ("eco", "eco", "mdi:leaf", True),
    ("clean", "clean", "mdi:broom", False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MitsubishiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        MitsubishiSwitch(entry.runtime_data, field, key, icon, powers_on)
        for field, key, icon, powers_on in SWITCHES
    )


class MitsubishiSwitch(SwitchEntity):
    """One on/off setting that's sent as part of the unit's full state."""

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(
        self, controller: AcController, field: str, key: str, icon: str, powers_on: bool
    ) -> None:
        self._controller = controller
        self._field = field
        self._powers_on = powers_on
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{controller.entry.entry_id}_{field}"
        self._attr_device_info = controller.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return getattr(self._controller.state, self._field)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._powers_on:
            self._controller.update(**{self._field: True, "power": True})
        else:
            self._controller.update(**{self._field: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._controller.update(**{self._field: False})
