"""The amule.add_link action, and error mapping shared by entities."""

from __future__ import annotations

from collections.abc import Awaitable

import probatio
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import AmuleError
from .const import ATTR_LINK, DOMAIN, SERVICE_ADD_LINK
from .coordinator import AmuleCoordinator

ADD_LINK_SCHEMA = probatio.Schema({probatio.Required(ATTR_LINK): probatio.All(cv.ensure_list, [cv.string])})


async def call[T](request: Awaitable[T]) -> T:
    """Await an app request, turning failures into errors Home Assistant shows to the user."""
    try:
        return await request
    except AmuleError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="request_failed", translation_placeholders={"error": str(err)}
        ) from err


def _coordinator(hass: HomeAssistant) -> AmuleCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    coordinator: AmuleCoordinator = entries[0].runtime_data
    return coordinator


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_link(service: ServiceCall) -> None:
        links = [link.strip() for value in service.data[ATTR_LINK] for link in value.splitlines() if link.strip()]
        bad = [link for link in links if not link.lower().startswith("ed2k://")]
        if not links or bad:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_link",
                translation_placeholders={"link": (bad or [""])[0][:80]},
            )
        coordinator = _coordinator(hass)
        await call(coordinator.api.add_links(links))
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ADD_LINK, add_link, schema=ADD_LINK_SCHEMA)
