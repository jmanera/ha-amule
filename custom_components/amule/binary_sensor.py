"""eD2k and Kad connectivity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmuleConfigEntry, AmuleCoordinator
from .entity import AmuleEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AmuleBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[dict[str, Any]], bool]


def _conn(name: str) -> Callable[[dict[str, Any]], bool]:
    return lambda data: bool(data["status"]["connection"][name])


BINARY_SENSORS = (
    AmuleBinarySensorDescription(
        key="ed2k_connected", device_class=BinarySensorDeviceClass.CONNECTIVITY, is_on_fn=_conn("ed2k_connected")
    ),
    AmuleBinarySensorDescription(
        key="kad_connected", device_class=BinarySensorDeviceClass.CONNECTIVITY, is_on_fn=_conn("kad_connected")
    ),
    AmuleBinarySensorDescription(
        key="low_id",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda data: bool(
            data["status"]["connection"]["ed2k_connected"] and not data["status"]["connection"]["ed2k_high_id"]
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmuleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(AmuleBinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class AmuleBinarySensor(AmuleEntity, BinarySensorEntity):
    entity_description: AmuleBinarySensorDescription

    def __init__(self, coordinator: AmuleCoordinator, description: AmuleBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.coordinator.data)
