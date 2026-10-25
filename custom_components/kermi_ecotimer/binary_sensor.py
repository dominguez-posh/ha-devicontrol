"""Binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as proto
from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator
from .entity import EcoTimerEntity


@dataclass(frozen=True, kw_only=True)
class EcoTimerBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[proto.EcoTimerState], bool]


BINARY_SENSORS: tuple[EcoTimerBinarySensorDescription, ...] = (
    EcoTimerBinarySensorDescription(
        key="heating",
        translation_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda s: s.relay,
    ),
    EcoTimerBinarySensorDescription(
        key="window_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda s: s.window_open,
    ),
    EcoTimerBinarySensorDescription(
        key="temperature_limit",
        translation_key="temperature_limit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.temperature_limit,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(EcoTimerBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class EcoTimerBinarySensor(EcoTimerEntity, BinarySensorEntity):
    entity_description: EcoTimerBinarySensorDescription

    def __init__(self, coordinator: EcoTimerCoordinator, description: EcoTimerBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)
