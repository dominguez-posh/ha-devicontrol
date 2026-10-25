"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import protocol as proto
from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator
from .entity import EcoTimerEntity

PHASE_OPTIONS = ["antifreeze", "eco", "comfort", "boost"]


def _phase(coordinator: EcoTimerCoordinator) -> str:
    state = coordinator.data
    if state.boost:
        return "boost"
    if phase := proto.ACTIVE_PHASES.get(state.active_phase):
        return phase
    mode = state.mode_at(dt_util.now())
    return proto.MODES[mode] if mode != proto.MODE_RESERVED else "antifreeze"


@dataclass(frozen=True, kw_only=True)
class EcoTimerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EcoTimerCoordinator], Any]


SENSORS: tuple[EcoTimerSensorDescription, ...] = (
    EcoTimerSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda c: c.current_temperature,
    ),
    EcoTimerSensorDescription(
        key="raw_temperature",
        translation_key="raw_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.data.actual,
    ),
    EcoTimerSensorDescription(
        key="comfort_temperature",
        translation_key="comfort_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda c: c.data.setpoint,
    ),
    EcoTimerSensorDescription(
        key="dial_position",
        translation_key="dial_position",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.dial_percent,
    ),
    EcoTimerSensorDescription(
        key="boost_remaining",
        translation_key="boost_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda c: c.data.boost_remaining if c.data.boost else 0,
    ),
    EcoTimerSensorDescription(
        key="phase",
        translation_key="phase",
        device_class=SensorDeviceClass.ENUM,
        options=PHASE_OPTIONS,
        value_fn=_phase,
    ),
    EcoTimerSensorDescription(
        key="adapter",
        translation_key="adapter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.adapter_name,
    ),
    EcoTimerSensorDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.rssi,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(EcoTimerSensor(entry.runtime_data, description) for description in SENSORS)


class EcoTimerSensor(EcoTimerEntity, SensorEntity):
    entity_description: EcoTimerSensorDescription

    def __init__(self, coordinator: EcoTimerCoordinator, description: EcoTimerSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)
