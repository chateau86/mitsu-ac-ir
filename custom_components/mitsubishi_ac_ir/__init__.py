"""Mitsubishi AC control through a Zigbee2MQTT IR blaster."""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import AcController, MitsubishiConfigEntry

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: MitsubishiConfigEntry) -> bool:
    controller = AcController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MitsubishiConfigEntry) -> bool:
    entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: MitsubishiConfigEntry) -> None:
    """Options changed (Configure page): reload to pick them up."""
    await hass.config_entries.async_reload(entry.entry_id)
