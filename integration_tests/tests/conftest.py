from __future__ import annotations

import copy
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.amule.const import DOMAIN

HOST = "abc123-amule"
BASE = f"http://{HOST}:8099/api"
ENTRY_DATA = {CONF_HOST: HOST, CONF_PORT: 8099, CONF_API_KEY: "secret-key"}

# A real /api/overview answer from the app (against the fake amuled), trimmed to four downloads.
OVERVIEW: dict[str, Any] = json.loads((Path(__file__).parent / "overview.json").read_text())


def overview(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(OVERVIEW)
    data.update(changes)
    return data


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    yield


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=ENTRY_DATA, title="aMule")


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    aioclient_mock.get(f"{BASE}/overview", json=OVERVIEW)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
