"""Kermi EcoTimer (Bluetooth) integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS
from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry) -> bool:
    coordinator = EcoTimerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: EcoTimerConfigEntry) -> None:
    # also called for title changes (rename); only a new polling interval needs a reload
    interval = timedelta(seconds=entry.options.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS))
    if entry.runtime_data.update_interval != interval:
        await hass.config_entries.async_reload(entry.entry_id)
