from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from ha_amule import discovery


def test_integration_key_is_created_once(tmp_path: Path) -> None:
    key = discovery.integration_key(tmp_path / "data")
    assert len(key) >= 32
    assert discovery.integration_key(tmp_path / "data") == key
    assert (tmp_path / "data" / "integration_key").stat().st_mode & 0o777 == 0o600
    (tmp_path / "data" / "integration_key").write_text("short")
    assert discovery.integration_key(tmp_path / "data") != "short"


async def test_announce_skips_outside_the_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert await discovery.announce(8099, "key") is False


async def test_announce_posts_host_port_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup")
    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "abc123-amule")
    with respx.mock(base_url="http://supervisor") as supervisor:
        route = supervisor.post("/discovery").mock(
            side_effect=[httpx.Response(500), httpx.Response(200, json={"result": "ok"})]
        )
        assert await discovery.announce(8099, "key", retry_delay=0) is True
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sup"
    assert json.loads(request.content) == {
        "service": "amule",
        "config": {"host": "abc123-amule", "port": 8099, "api_key": "key"},
    }


async def test_announce_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup")
    with respx.mock(base_url="http://supervisor") as supervisor:
        supervisor.post("/discovery").mock(side_effect=httpx.ConnectError("down"))
        assert await discovery.announce(8099, "key", attempts=2, retry_delay=0) is False
