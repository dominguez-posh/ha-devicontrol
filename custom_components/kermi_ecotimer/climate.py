"""Climate entity: heat/off plus presets that map onto the device week program.

The comfort temperature is set with the dial on the device; Home Assistant chooses
which phase (comfort, eco, antifreeze) applies by writing the week program.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import protocol as proto
from .const import DAYS, DOMAIN
from .coordinator import EcoTimerConfigEntry, EcoTimerCoordinator
from .entity import EcoTimerEntity

PRESET_PROGRAM = "program"
PERIOD_MODES = ("antifreeze", "eco", "comfort")

PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required("start"): cv.string,
        vol.Required("end"): cv.string,
        vol.Required("mode"): vol.In(PERIOD_MODES),
    }
)
SET_PROGRAM_SCHEMA = {
    vol.Required("days"): vol.All(cv.ensure_list, [vol.In(DAYS)]),
    vol.Optional("base_mode", default="eco"): vol.In(PERIOD_MODES),
    vol.Optional("periods", default=[]): vol.All(cv.ensure_list, [PERIOD_SCHEMA]),
    vol.Optional("activate", default=True): cv.boolean,
}


async def async_setup_entry(hass: HomeAssistant, entry: EcoTimerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([EcoTimerClimate(entry.runtime_data)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("set_program", SET_PROGRAM_SCHEMA, "async_set_program")
    platform.async_register_entity_service(
        "write_raw",
        {vol.Required("patches"): {vol.All(vol.Coerce(int), vol.Range(min=0, max=proto.SCHEDULE_OFFSET - 1)):
                                   vol.All(vol.Coerce(int), vol.Range(min=0, max=255))}},
        "async_write_raw",
    )
    platform.async_register_entity_service(
        "rename",
        {
            vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=64)),
            vol.Optional("device_name"): vol.All(cv.string, vol.Length(min=1, max=proto.DEVICE_NAME_MAX_BYTES)),
        },
        "async_rename",
    )


class EcoTimerClimate(EcoTimerEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "ecotimer"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_PROGRAM, PRESET_BOOST]
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: EcoTimerCoordinator) -> None:
        super().__init__(coordinator, "climate")
        self._last_preset = PRESET_PROGRAM if coordinator.program else PRESET_COMFORT

    @property
    def _state(self) -> proto.EcoTimerState:
        return self.coordinator.data

    @property
    def current_temperature(self) -> float:
        return self.coordinator.current_temperature

    @property
    def target_temperature(self) -> float:
        state = self._state
        if state.boost:
            return state.setpoint
        return state.temperature_for_mode(state.mode_at(dt_util.now()))

    @property
    def hvac_mode(self) -> HVACMode:
        state = self._state
        if not state.boost and state.uniform_mode() == proto.MODE_ANTIFREEZE:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self._state.relay:
            return HVACAction.HEATING
        return HVACAction.OFF if self.hvac_mode == HVACMode.OFF else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        state = self._state
        if state.boost:
            return PRESET_BOOST
        uniform = state.uniform_mode()
        if uniform == proto.MODE_COMFORT:
            return PRESET_COMFORT
        if uniform == proto.MODE_ECO:
            return PRESET_ECO
        if uniform is None:
            return PRESET_PROGRAM
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        return {
            "comfort_temperature": state.setpoint,
            "eco_temperature": state.eco_temperature,
            "boost_remaining": state.boost_remaining if state.boost else 0,
            "program": {
                DAYS[i]: ", ".join(f"{a}-{b} {m}" for a, b, m in proto.day_summary(day))
                for i, day in enumerate(state.program)
            },
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_write(boost=False, program=proto.uniform_program(proto.MODE_ANTIFREEZE))
        else:
            await self.async_set_preset_mode(self._last_preset)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_BOOST:
            await self.coordinator.async_write(boost=True)
            return
        if preset_mode == PRESET_PROGRAM:
            if not self.coordinator.program:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="no_program"
                )
            program = self.coordinator.program
        else:
            mode = proto.MODE_COMFORT if preset_mode == PRESET_COMFORT else proto.MODE_ECO
            program = proto.uniform_program(mode)
        self._last_preset = preset_mode
        await self.coordinator.async_write(boost=False, program=program)

    async def async_write_raw(self, patches: dict[int, int]) -> None:
        """Diagnostics: write the image with single header bytes replaced."""
        await self.coordinator.async_write(raw_patches=patches)

    async def async_rename(self, name: str, device_name: str | None = None) -> None:
        """Rename the thermostat (Bluetooth name, Home Assistant device and entry)."""
        await self.coordinator.async_rename(name, device_name)

    async def async_set_program(self, days: list[str], base_mode: str, periods: list[dict[str, str]],
                                activate: bool) -> None:
        """Define the week program for the given days (quarter-hour resolution)."""
        base = self.coordinator.program or self._state.program
        program = [list(day) for day in base]
        for day in days:
            slots = [proto.MODE_BY_NAME[base_mode]] * proto.SLOTS_PER_DAY
            for period in periods:
                try:
                    start, end = proto.parse_slot(period["start"]), proto.parse_slot(period["end"])
                except ValueError as err:
                    raise ServiceValidationError(str(err)) from err
                if start >= end:
                    raise ServiceValidationError(f"{period['start']}-{period['end']}: start must be before end")
                slots[start:end] = [proto.MODE_BY_NAME[period["mode"]]] * (end - start)
            program[DAYS.index(day)] = slots
        await self.coordinator.async_save_program(program)
        if activate:
            self._last_preset = PRESET_PROGRAM
            await self.coordinator.async_write(boost=False, program=program)
        else:
            self.async_write_ha_state()
