"""Climate entity for one AC unit."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import MAX_TEMP, MIN_TEMP
from .controller import AcController, MitsubishiConfigEntry
from .protocol import Fan, Mode, Vane

HVAC_TO_MODE = {HVACMode.COOL: Mode.COOL, HVACMode.DRY: Mode.DRY, HVACMode.FAN_ONLY: Mode.FAN}
MODE_TO_HVAC = {v: k for k, v in HVAC_TO_MODE.items()}

FAN_MODES = {"auto": Fan.AUTO, "1": Fan.SPEED_1, "2": Fan.SPEED_2,
             "3": Fan.SPEED_3, "4": Fan.SPEED_4, "silent": Fan.SILENT}
SWING_MODES = {"auto": Vane.AUTO, "1": Vane.POS_1, "2": Vane.POS_2, "3": Vane.POS_3,
               "4": Vane.POS_4, "5": Vane.POS_5, "swing": Vane.SWING}

PRESET_NONE, PRESET_BOOST, PRESET_ECO = "none", "boost", "eco"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MitsubishiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([MitsubishiClimate(entry.runtime_data)])


class MitsubishiClimate(ClimateEntity):
    """The AC as a climate entity. State is assumed: IR can't report back."""

    _attr_has_entity_name = True
    _attr_name = None                   # use the device name
    _attr_assumed_state = True
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_TO_MODE]
    _attr_fan_modes = list(FAN_MODES)
    _attr_swing_modes = list(SWING_MODES)
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_ECO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, controller: AcController) -> None:
        self._controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_climate"
        self._attr_device_info = controller.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.add_listener(self.async_write_ha_state))
        if sensor := self._controller.temperature_sensor:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [sensor], self._sensor_changed)
            )

    @callback
    def _sensor_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    # --- state ---

    @property
    def hvac_mode(self) -> HVACMode:
        s = self._controller.state
        if not s.power:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(s.mode, HVACMode.COOL)

    @property
    def target_temperature(self) -> float:
        return self._controller.state.temperature

    @property
    def current_temperature(self) -> float | None:
        sensor = self._controller.temperature_sensor
        if not sensor or not (st := self.hass.states.get(sensor)):
            return None
        try:
            return float(st.state)
        except ValueError:              # unknown / unavailable
            return None

    @property
    def fan_mode(self) -> str:
        fan = self._controller.state.fan
        return next(k for k, v in FAN_MODES.items() if v == fan)

    @property
    def swing_mode(self) -> str:
        vane = self._controller.state.vane
        return next(k for k, v in SWING_MODES.items() if v == vane)

    @property
    def preset_mode(self) -> str:
        s = self._controller.state
        if s.turbo:
            return PRESET_BOOST
        return PRESET_ECO if s.eco else PRESET_NONE

    # --- commands ---

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            self._controller.update(power=False)
        else:
            self._controller.update(power=True, mode=HVAC_TO_MODE[hvac_mode])

    async def async_turn_on(self) -> None:
        self._controller.update(power=True)

    async def async_turn_off(self) -> None:
        self._controller.update(power=False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        changes: dict[str, Any] = {}
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            changes["temperature"] = max(MIN_TEMP, min(MAX_TEMP, round(temp)))
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            if hvac_mode == HVACMode.OFF:
                changes["power"] = False
            else:
                changes.update(power=True, mode=HVAC_TO_MODE[hvac_mode])
        if changes:
            self._controller.update(**changes)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._controller.update(fan=FAN_MODES[fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self._controller.update(vane=SWING_MODES[swing_mode])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Presets are exclusive; the Turbo and Eco switches can still mix them
        self._controller.update(
            turbo=preset_mode == PRESET_BOOST, eco=preset_mode == PRESET_ECO
        )
