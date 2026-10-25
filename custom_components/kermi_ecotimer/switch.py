"""Boost switch (the device runs a boost for a fixed 60 minutes)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator
from .entity import EcoTimerEntity


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([EcoTimerBoostSwitch(entry.runtime_data)])


class EcoTimerBoostSwitch(EcoTimerEntity, SwitchEntity):
    _attr_translation_key = "boost"

    def __init__(self, coordinator: EcoTimerCoordinator) -> None:
        super().__init__(coordinator, "boost")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.boost

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(boost=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(boost=False)
