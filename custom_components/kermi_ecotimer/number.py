"""Settings: eco offset (written to the device) and temperature calibration (Home Assistant only)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as proto
from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator
from .entity import EcoTimerEntity


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([EcoTimerEcoOffset(entry.runtime_data), EcoTimerTemperatureOffset(entry.runtime_data)])


class EcoTimerEcoOffset(EcoTimerEntity, NumberEntity):
    """How far eco is below the comfort temperature set with the dial."""

    _attr_translation_key = "eco_offset"
    # no temperature device class: these are differences, HA would convert them as absolute temperatures
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = proto.ECO_OFFSET_MIN
    _attr_native_max_value = proto.ECO_OFFSET_MAX
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EcoTimerCoordinator) -> None:
        super().__init__(coordinator, "eco_offset")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.eco_offset

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(eco_offset=value)


class EcoTimerTemperatureOffset(EcoTimerEntity, NumberEntity):
    """Calibration added to the measured temperature; the device itself is not changed."""

    _attr_translation_key = "temperature_offset"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -5.0
    _attr_native_max_value = 5.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EcoTimerCoordinator) -> None:
        super().__init__(coordinator, "temperature_offset")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float:
        return self.coordinator.temperature_offset

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_temperature_offset(value)
