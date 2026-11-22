"""Connect to or disconnect from the eD2k and Kad networks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmuleConfigEntry, AmuleCoordinator
from .entity import AmuleEntity
from .services import call

PARALLEL_UPDATES = 1

# Switch key -> (API network name, connection flags that mean "on")
NETWORKS = {
    "ed2k": ("ed2k", ("ed2k_connected", "ed2k_connecting")),
    "kad": ("kad", ("kad_running",)),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmuleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(AmuleNetworkSwitch(entry.runtime_data, key) for key in NETWORKS)


class AmuleNetworkSwitch(AmuleEntity, SwitchEntity):
    def __init__(self, coordinator: AmuleCoordinator, key: str) -> None:
        super().__init__(coordinator, f"{key}_network")
        self._network, self._flags = NETWORKS[key]

    @property
    def is_on(self) -> bool:
        connection = self.coordinator.data["status"]["connection"]
        return any(connection[flag] for flag in self._flags)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await call(self.coordinator.api.set_network(self._network, True))
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await call(self.coordinator.api.set_network(self._network, False))
        await self.coordinator.async_request_refresh()
