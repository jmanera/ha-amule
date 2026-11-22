"""Bulk actions on the download queue."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmuleConfigEntry, AmuleCoordinator
from .entity import AmuleEntity
from .services import call

PARALLEL_UPDATES = 1

BUTTONS = ("pause_all", "resume_all", "clear_completed")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmuleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(AmuleButton(entry.runtime_data, key) for key in BUTTONS)


class AmuleButton(AmuleEntity, ButtonEntity):
    def __init__(self, coordinator: AmuleCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key

    async def async_press(self) -> None:
        api = self.coordinator.api
        if self._key == "clear_completed":
            await call(api.clear_completed())
        elif self._key == "pause_all":
            if hashes := self.coordinator.hashes("downloading", "waiting"):
                await call(api.downloads_action("pause", hashes))
        elif hashes := self.coordinator.hashes("paused", "stopped"):
            await call(api.downloads_action("resume", hashes))
        await self.coordinator.async_request_refresh()
