"""Polls the app and turns finished or failed downloads into Home Assistant events."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AmuleApi, AmuleAuthError, AmuleError
from .const import DOMAIN, EVENT_DOWNLOAD_COMPLETED, EVENT_DOWNLOAD_FAILED, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type AmuleConfigEntry = ConfigEntry[AmuleCoordinator]

_EVENTS = {"completed": EVENT_DOWNLOAD_COMPLETED, "error": EVENT_DOWNLOAD_FAILED}


class AmuleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: AmuleConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AmuleConfigEntry, api: AmuleApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.api = api
        # File hash -> last seen state. None until the first poll, so downloads that finished
        # while Home Assistant was down don't fire events on startup.
        self._states: dict[str, str] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.overview()
        except AmuleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AmuleError as err:
            raise UpdateFailed(f"Error talking to the aMule app: {err}") from err
        self._fire_events(data["downloads"])
        return data

    def _fire_events(self, downloads: list[dict[str, Any]]) -> None:
        if self._states is not None:
            for download in downloads:
                state = download["state"]
                if state != self._states.get(download["hash"]) and (event := _EVENTS.get(state)):
                    self.hass.bus.async_fire(
                        event,
                        {
                            "name": download["name"],
                            "hash": download["hash"],
                            "size": download["size"],
                            "link": download["link"],
                        },
                    )
        self._states = {d["hash"]: d["state"] for d in downloads}

    def hashes(self, *states: str) -> list[str]:
        return [d["hash"] for d in self.data["downloads"] if d["state"] in states]
