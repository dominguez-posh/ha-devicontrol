"""Config flow: Bluetooth discovery or pick from the devices Home Assistant currently sees."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from . import protocol as proto
from .const import (
    CONF_POLL_SECONDS,
    CONF_RATED_POWER,
    DEFAULT_POLL_SECONDS,
    DEFAULT_RATED_POWER,
    DOMAIN,
    MAX_POLL_SECONDS,
    MAX_RATED_POWER,
    MIN_POLL_SECONDS,
)


def _is_ecotimer(info: BluetoothServiceInfoBleak) -> bool:
    data = info.manufacturer_data.get(proto.MANUFACTURER_ID)
    return data is not None and data.startswith(proto.MANUFACTURER_DATA)


def _title(info: BluetoothServiceInfoBleak) -> str:
    return info.name if info.name and info.name != info.address else f"EcoTimer {info.address[-5:]}"


class EcoTimerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_ecotimer(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self.async_create_entry(title=_title(self._discovery), data={})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _title(self._discovery), "address": self._discovery.address},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            info = self._discovered[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=_title(info), data={})

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in configured and _is_ecotimer(info):
                self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {a: f"{_title(i)} ({a})" for a, i in self._discovered.items()}
                    )
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> EcoTimerOptionsFlow:
        return EcoTimerOptionsFlow()


class EcoTimerOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_SECONDS, default=options.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_SECONDS, max=MAX_POLL_SECONDS)),
                    vol.Required(
                        CONF_RATED_POWER, default=options.get(CONF_RATED_POWER, DEFAULT_RATED_POWER)
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RATED_POWER)),
                }
            ),
        )
