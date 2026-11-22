from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.amule.const import DOMAIN, EVENT_DOWNLOAD_COMPLETED, EVENT_DOWNLOAD_FAILED

from .conftest import BASE, OVERVIEW, overview

LINK = "ed2k://|file|debian.iso|790626304|0AD178854C9C32318FFAE8A358E80373|/"


async def test_entities(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED

    down = hass.states.get("sensor.amule_download_speed")
    assert down is not None
    assert float(down.state) == pytest.approx(0.508)  # MB/s
    assert down.attributes["unit_of_measurement"] == "MB/s"
    up = hass.states.get("sensor.amule_upload_speed")
    assert up is not None
    assert float(up.state) == pytest.approx(38.0)  # kB/s

    for entity_id, value in {
        "sensor.amule_active_downloads": "1",
        "sensor.amule_queued_downloads": "1",
        "sensor.amule_paused_downloads": "1",
        "sensor.amule_completed_downloads": "1",
        "sensor.amule_failed_downloads": "0",
        "sensor.amule_downloads_in_queue": "4",
        "sensor.amule_upload_queue": "17",
        "sensor.amule_shared_files": "1",
        "sensor.amule_ed2k_status": "high_id",
        "sensor.amule_kad_status": "connected",
        "sensor.amule_ed2k_server": "eMule Sunrise",
        "sensor.amule_kad_nodes": "312",
        "binary_sensor.amule_ed2k_connection": "on",
        "binary_sensor.amule_kad_connection": "on",
        "binary_sensor.amule_low_id": "off",
        "switch.amule_ed2k_network": "on",
        "switch.amule_kad_network": "on",
        "number.amule_download_limit": "0",
        "number.amule_upload_limit": "0",
    }.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == value, entity_id

    session = hass.states.get("sensor.amule_downloaded_this_session")
    assert session is not None
    assert float(session.state) == pytest.approx(9.88, abs=0.01)  # GB

    active = hass.states.get("sensor.amule_active_downloads")
    assert active is not None
    assert active.attributes["downloads"][0]["name"] == "debian-13.2.0-amd64-netinst.iso"
    server = hass.states.get("sensor.amule_ed2k_server")
    assert server is not None
    assert server.attributes["address"] == "176.123.5.89:4725"

    # Off by default: noisy and rarely useful.
    entry = er.async_get(hass).async_get("sensor.amule_sources")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_low_id_and_disconnected_states(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    data = overview()
    connection = data["status"]["connection"]
    connection.update(ed2k_high_id=False, kad_connected=False, kad_firewalled=False, kad_running=True)
    aioclient_mock.get(f"{BASE}/overview", json=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.amule_ed2k_status").state == "low_id"  # type: ignore[union-attr]
    assert hass.states.get("binary_sensor.amule_low_id").state == "on"  # type: ignore[union-attr]
    assert hass.states.get("sensor.amule_kad_status").state == "connecting"  # type: ignore[union-attr]


async def test_setup_retries_when_app_is_down(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/overview", status=503, json={"detail": "aMule is starting"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/overview", status=403)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_events_for_finished_downloads(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    events: list[Event] = []

    @callback
    def record(event: Event) -> None:
        events.append(event)

    hass.bus.async_listen(EVENT_DOWNLOAD_COMPLETED, record)
    hass.bus.async_listen(EVENT_DOWNLOAD_FAILED, record)

    data = overview()
    downloading, waiting = data["downloads"][0], data["downloads"][1]
    downloading["state"] = "completed"
    waiting["state"] = "error"
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/overview", json=data)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()

    # The download that was already complete at startup fires nothing.
    assert [(e.event_type, e.data["name"]) for e in events] == [
        (EVENT_DOWNLOAD_COMPLETED, downloading["name"]),
        (EVENT_DOWNLOAD_FAILED, waiting["name"]),
    ]
    assert events[0].data["hash"] == downloading["hash"]
    assert events[0].data["link"].startswith("ed2k://")


async def test_add_link_action(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/downloads", status=202)
    await hass.services.async_call(DOMAIN, "add_link", {"link": f"{LINK}\n  {LINK.lower()} "}, blocking=True)
    posted = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert posted[-1][2] == {"links": [LINK, LINK.lower()]}

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "add_link", {"link": ["magnet:?xt=urn:btih:abc"]}, blocking=True)


async def test_add_link_reports_app_errors(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/downloads", status=409, json={"detail": "Invalid link or already on list."})
    with pytest.raises(HomeAssistantError, match="already on list"):
        await hass.services.async_call(DOMAIN, "add_link", {"link": LINK}, blocking=True)


async def test_add_link_needs_a_loaded_entry(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "add_link", {"link": LINK}, blocking=True)


async def test_controls(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    for path in ("network/ed2k", "network/kad", "limits", "downloads/pause", "downloads/resume"):
        aioclient_mock.post(f"{BASE}/{path}", status=204)
    aioclient_mock.post(f"{BASE}/downloads/clear-completed", status=204)

    async def last_post() -> tuple[str, object]:
        await hass.async_block_till_done()
        call = [c for c in aioclient_mock.mock_calls if c[0] == "POST"][-1]
        return str(call[1]).removeprefix(f"{BASE}/"), call[2]

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.amule_kad_network"}, blocking=True)
    assert await last_post() == ("network/kad", {"enabled": False})
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.amule_ed2k_network"}, blocking=True)
    assert await last_post() == ("network/ed2k", {"enabled": True})

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.amule_download_limit", "value": 500}, blocking=True
    )
    assert await last_post() == ("limits", {"download_kbps": 500})

    downloading, waiting, paused = (d["hash"] for d in OVERVIEW["downloads"][:3])
    await hass.services.async_call("button", "press", {"entity_id": "button.amule_pause_all_downloads"}, blocking=True)
    assert await last_post() == ("downloads/pause", {"hashes": [downloading, waiting]})
    await hass.services.async_call("button", "press", {"entity_id": "button.amule_resume_all_downloads"}, blocking=True)
    assert await last_post() == ("downloads/resume", {"hashes": [paused]})
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.amule_clear_completed_downloads"}, blocking=True
    )
    assert (await last_post())[0] == "downloads/clear-completed"


async def test_control_errors_are_reported(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/network/kad", exc=TimeoutError())
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.amule_kad_network"}, blocking=True)
