from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fake_amuled import FakeAmuled

from ha_amule.amule import AmuleClient
from ha_amule.api import create_app
from ha_amule.config import Settings
from ha_amule.ec.client import ECClient

LINK = "ed2k://|file|test.iso|1000000|0123456789ABCDEF0123456789ABCDEF|/"


def settings(tmp_path: Path, **changes: object) -> Settings:
    return Settings(data_dir=tmp_path, ec_host="127.0.0.1", ec_password="secret", **changes)  # type: ignore[arg-type]


@pytest.fixture
async def http(tmp_path: Path, amule: AmuleClient) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings(tmp_path), amule)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as client:
        yield client


async def test_overview(http: httpx.AsyncClient) -> None:
    body = (await http.get("/api/overview")).json()
    assert body["status"]["amule_version"] == "2.3.3"
    assert body["status"]["connection"]["ed2k_high_id"] is True
    assert body["stats"]["download_speed"] == 508_000
    assert body["counts"] == {"total": 5, "downloading": 2, "waiting": 1, "paused": 1, "completed": 1, "error": 0}
    assert len(body["downloads"]) == 5


async def test_download_actions(http: httpx.AsyncClient) -> None:
    assert (await http.post("/api/downloads", json={"links": [LINK, " "]})).status_code == 202
    conflict = await http.post("/api/downloads", json={"links": [LINK]})
    assert conflict.status_code == 409
    assert "already on list" in conflict.json()["detail"]
    invalid = await http.post("/api/downloads", json={"links": ["magnet:?xt=abc"]})
    assert invalid.status_code == 422
    assert (await http.post("/api/downloads", json={"links": ["  "]})).status_code == 422

    downloads = (await http.get("/api/downloads")).json()
    target = next(d["hash"] for d in downloads if d["name"] == "test.iso")
    for action in ("pause", "resume", "stop"):
        assert (await http.post(f"/api/downloads/{action}", json={"hashes": [target]})).status_code == 204
    body = {"hashes": [target], "priority": "high"}
    assert (await http.post("/api/downloads/priority", json=body)).status_code == 204
    assert (await http.post("/api/downloads/cancel", json={"hashes": [target]})).status_code == 204
    assert (await http.post("/api/downloads/clear-completed")).status_code == 204
    assert (await http.post("/api/downloads/pause", json={"hashes": ["nothex"]})).status_code == 422
    missing = await http.post("/api/downloads/pause", json={"hashes": ["0" * 32]})
    assert missing.status_code == 409


async def test_search_flow(http: httpx.AsyncClient) -> None:
    assert (await http.post("/api/search", json={"query": "x"})).status_code == 422
    started = await http.post("/api/search", json={"query": "linux", "scope": "global", "min_size": 1024})
    assert started.status_code == 202
    status = (await http.get("/api/search")).json()
    assert status["running"] is True
    while (status := (await http.get("/api/search")).json())["progress"]:
        pass
    hashes = [r["hash"] for r in status["results"][:2]]
    assert (await http.post("/api/search/download", json={"hashes": hashes})).status_code == 202
    assert (await http.delete("/api/search")).status_code == 204


async def test_other_views(http: httpx.AsyncClient) -> None:
    assert (await http.get("/api/uploads")).json()[0]["client"] == "aMule 2.3.3"
    assert (await http.get("/api/shared")).json()[0]["name"].startswith("ubuntu")
    assert (await http.post("/api/shared/reload")).status_code == 204
    assert len((await http.get("/api/servers")).json()) == 2
    assert any("aMuleD" in line for line in (await http.get("/api/log")).json())
    assert (await http.get("/api/nope")).status_code == 404


async def test_network_and_limits(http: httpx.AsyncClient, fake: FakeAmuled) -> None:
    assert (await http.post("/api/network/ed2k", json={"enabled": False})).status_code == 204
    assert (await http.post("/api/network/kad", json={"enabled": False})).status_code == 204
    assert not fake.ed2k and not fake.kad
    assert (await http.post("/api/network/ed2k", json={"enabled": True})).status_code == 204
    assert (await http.post("/api/network/kad", json={"enabled": True})).status_code == 204
    assert fake.ed2k and fake.kad
    body = {"address": "176.123.5.89:4725"}
    assert (await http.post("/api/network/ed2k/connect", json=body)).status_code == 204
    assert (await http.post("/api/network/ed2k/connect", json={"address": "evil"})).status_code == 422
    assert (await http.post("/api/limits", json={"download_kbps": 300})).status_code == 204
    assert fake.limits == (300, 0)
    assert (await http.post("/api/limits", json={"download_kbps": -1})).status_code == 422


async def test_amuled_down(tmp_path: Path) -> None:
    dead = AmuleClient(ECClient("127.0.0.1", 1, "secret", timeout=1))
    app = create_app(settings(tmp_path), dead)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as http:
        response = await http.get("/api/overview")
        assert response.status_code == 503
        assert response.json()["detail"] == "aMule is starting"
        assert (await http.get("/api/log")).json() == []


async def test_wrong_password_is_a_bad_gateway(tmp_path: Path, fake: FakeAmuled) -> None:
    client = AmuleClient(ECClient("127.0.0.1", fake.port, "wrong", timeout=2))  # type: ignore[attr-defined]
    app = create_app(settings(tmp_path), client)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as http:
        response = await http.get("/api/overview")
        assert response.status_code == 502


async def test_only_ingress_or_the_integration_get_in(tmp_path: Path, amule: AmuleClient) -> None:
    app = create_app(settings(tmp_path, ingress_only=True), amule)
    key = (tmp_path / "integration_key").read_text()
    outsider = httpx.ASGITransport(app=app, client=("192.168.1.50", 5555))
    async with httpx.AsyncClient(transport=outsider, base_url="http://app") as http:
        assert (await http.get("/api/overview")).status_code == 403
        assert (await http.get("/api/overview", headers={"Authorization": "Bearer nope"})).status_code == 403
        assert (await http.get("/api/overview", headers={"Authorization": f"Bearer {key}"})).status_code == 200
    ingress = httpx.ASGITransport(app=app, client=("172.30.32.2", 5555))
    async with httpx.AsyncClient(transport=ingress, base_url="http://app") as http:
        assert (await http.get("/api/overview")).status_code == 200
        page = await http.get("/")
        assert page.status_code == 200
        assert "<title>aMule</title>" in page.text
