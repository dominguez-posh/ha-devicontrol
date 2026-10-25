"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
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
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda c: (c.rated_power if c.data.relay else 0) if c.rated_power else None,
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
        value_fn=lambda c: c.boost_remaining,
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
    coordinator = entry.runtime_data
    async_add_entities([*(EcoTimerSensor(coordinator, d) for d in SENSORS), EcoTimerEnergySensor(coordinator)])


class EcoTimerSensor(EcoTimerEntity, SensorEntity):
    entity_description: EcoTimerSensorDescription

    def __init__(self, coordinator: EcoTimerCoordinator, description: EcoTimerSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)


# Longer gaps between updates (connection lost) are not counted.
MAX_ENERGY_GAP_SECONDS = 300


class EcoTimerEnergySensor(EcoTimerEntity, RestoreSensor):
    """Energy from relay-on time x rated power; survives restarts, usable in the energy dashboard."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: EcoTimerCoordinator) -> None:
        super().__init__(coordinator, "energy")
        self._energy = 0.0
        self._last_update: datetime | None = None
        self._relay_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) and last.native_value is not None:
            self._energy = float(last.native_value)
        self._last_update = dt_util.utcnow()
        self._relay_on = self.coordinator.data.relay

    def _handle_coordinator_update(self) -> None:
        now = dt_util.utcnow()
        if not self.coordinator.last_update_success:
            self._last_update = None
        else:
            if self._last_update is not None and self._relay_on:
                seconds = (now - self._last_update).total_seconds()
                if seconds <= MAX_ENERGY_GAP_SECONDS:
                    self._energy += self.coordinator.rated_power * seconds / 3_600_000
            self._last_update = now
            self._relay_on = self.coordinator.data.relay
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return round(self._energy, 4) if self.coordinator.rated_power else None
