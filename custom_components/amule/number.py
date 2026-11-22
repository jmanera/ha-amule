"""Download and upload speed limits."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmuleConfigEntry, AmuleCoordinator
from .entity import AmuleEntity
from .services import call

PARALLEL_UPDATES = 1

LIMITS = {"download_limit": "download", "upload_limit": "upload"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmuleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(AmuleLimit(entry.runtime_data, key) for key in LIMITS)


class AmuleLimit(AmuleEntity, NumberEntity):
    """Speed limit in kB/s; 0 means unlimited. Lasts until the app restarts."""

    _attr_device_class = NumberDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.KILOBYTES_PER_SECOND
    _attr_native_min_value = 0
    _attr_native_max_value = 100_000
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AmuleCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._direction = LIMITS[key]

    @property
    def native_value(self) -> float:
        limit: int = self.coordinator.data["stats"][f"{self._direction}_limit"]
        return round(limit / 1024)

    async def async_set_native_value(self, value: float) -> None:
        await call(self.coordinator.api.set_limits(**{f"{self._direction}_kbps": int(value)}))
        await self.coordinator.async_request_refresh()
