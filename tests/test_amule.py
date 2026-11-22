from __future__ import annotations

import asyncio

import pytest
from fake_amuled import PS_COMPLETE, FakeAmuled

from ha_amule.amule import ActionFailedError, AmuleClient, is_noise
from ha_amule.ec.client import ECAuthError, ECClient, ECError
from ha_amule.ec.codes import Op, Tag
from ha_amule.ec.packet import ECPacket


async def test_stats_and_connection(amule: AmuleClient) -> None:
    stats, connection = await amule.stats()
    assert stats.download_speed == 508_000
    assert stats.total_received == 9_876_543_210
    assert stats.kad_nodes == 312
    assert connection.ed2k_connected
    assert connection.ed2k_high_id
    assert connection.server is not None
    assert connection.server.name == "eMule Sunrise"
    assert connection.server.address == "176.123.5.89:4725"
    assert connection.kad_connected
    assert not connection.kad_firewalled
    assert amule.ec.server_version == "2.3.3"
    assert any("aMuleD" in line for line in amule.log)


async def test_downloads(amule: AmuleClient, fake: FakeAmuled) -> None:
    downloads = {d.name: d for d in await amule.downloads()}
    debian = downloads["debian-13.2.0-amd64-netinst.iso"]
    assert debian.state == "downloading"
    assert debian.progress == pytest.approx(64.76)
    assert debian.priority == "normal"
    assert debian.auto_priority
    assert debian.link.startswith("ed2k://|file|debian")
    assert downloads["Sintel.2010.4k.mkv"].state == "waiting"
    assert downloads["LibreOffice_25.8.2_Linux_x86-64_deb.tar.gz"].state == "paused"
    done = downloads["ubuntu-24.04.3-desktop-amd64.iso"]
    assert (done.state, done.progress) == ("completed", 100.0)

    await amule.pause([debian.hash])
    await amule.set_priority([debian.hash], "high")
    after = {d.hash: d for d in await amule.downloads()}[debian.hash]
    assert (after.state, after.priority, after.auto_priority) == ("paused", "high", False)
    await amule.resume([debian.hash])
    await amule.set_priority([debian.hash], "auto")
    assert {d.hash: d for d in await amule.downloads()}[debian.hash].auto_priority

    await amule.cancel([debian.hash])
    await amule.clear_completed()
    names = {d.name for d in await amule.downloads()}
    assert "debian-13.2.0-amd64-netinst.iso" not in names
    assert all(f.status != PS_COMPLETE for f in fake.downloads)

    with pytest.raises(ActionFailedError, match="FileHash not found"):
        await amule.pause([debian.hash])


async def test_add_links(amule: AmuleClient) -> None:
    link = "ed2k://|file|test.iso|1000000|0123456789ABCDEF0123456789ABCDEF|/"
    await amule.add_links([f"  {link} "])
    assert any(d.name == "test.iso" for d in await amule.downloads())
    with pytest.raises(ActionFailedError, match="already on list"):
        await amule.add_links([link])


async def test_search(amule: AmuleClient, fake: FakeAmuled) -> None:
    idle = await amule.search_status()
    assert not idle.running
    await amule.search("linux", scope="kad", file_type="Iso", extension=".iso", min_size=1, max_size=9, availability=2)
    search = fake.requests[-1].tags[0]
    assert search.value == 2  # Kad
    assert search.str_of(Tag.SEARCH_NAME) == "linux"
    assert search.str_of(Tag.SEARCH_FILE_TYPE) == "Iso"
    assert search.str_of(Tag.SEARCH_EXTENSION) == "iso"
    assert (search.int_of(Tag.SEARCH_MIN_SIZE), search.int_of(Tag.SEARCH_MAX_SIZE)) == (1, 9)
    assert search.int_of(Tag.SEARCH_AVAILABILITY) == 2

    first = await amule.search_status()
    assert first.running
    assert first.progress == 36
    assert len(first.results) == 2
    while (status := await amule.search_status()).progress:
        pass
    assert len(status.results) == 4
    best = max(status.results, key=lambda r: r.sources)
    assert best.name == "linux 1080p WEB-DL.mkv"
    assert best.known == "new"

    await amule.download_results([best.hash])
    assert any(d.name == best.name for d in await amule.downloads())
    await amule.stop_search()
    assert not (await amule.search_status()).running
    await amule.search("any type", file_type="Any")
    assert fake.requests[-1].tags[0].str_of(Tag.SEARCH_FILE_TYPE) == ""


async def test_uploads_shared_and_servers(amule: AmuleClient) -> None:
    (upload,) = await amule.uploads()
    assert (upload.client, upload.speed, upload.file) == ("aMule 2.3.3", 38_000, "ubuntu-24.04.3-desktop-amd64.iso")
    (shared,) = await amule.shared_files()
    assert shared.name == "ubuntu-24.04.3-desktop-amd64.iso"
    assert shared.priority == "auto"
    await amule.reload_shared()
    servers = await amule.servers()
    assert [s.name for s in servers] == ["eMule Sunrise", "eNode"]
    assert servers[0].users == 54_910


async def test_network_controls(amule: AmuleClient, fake: FakeAmuled) -> None:
    await amule.disconnect_ed2k()
    await amule.stop_kad()
    _, connection = await amule.stats()
    assert not connection.ed2k_connected
    assert connection.ed2k_id is None
    assert not connection.kad_running
    await amule.connect_ed2k("176.123.5.89:4725")
    assert fake.requests[-1].tags[0].value == "176.123.5.89:4725"
    await amule.start_kad()
    _, connection = await amule.stats()
    assert connection.ed2k_connected
    assert connection.kad_connected

    await amule.set_limits(download_kbps=500)
    await amule.set_limits(upload_kbps=40)
    await amule.set_limits()
    stats, _ = await amule.stats()
    assert (stats.download_limit, stats.upload_limit) == (500 * 1024, 40 * 1024)
    await amule.update_servers("http://example.invalid/server.met")
    await amule.update_kad_nodes("http://example.invalid/nodes.dat")


async def test_wrong_password(fake: FakeAmuled) -> None:
    client = ECClient("127.0.0.1", fake.port, "wrong", timeout=5)  # type: ignore[attr-defined]
    with pytest.raises(ECAuthError, match="Authentication failed"):
        await client.request(ECPacket(Op.NOOP))
    await client.close()


async def test_unknown_op_and_unreachable(amule: AmuleClient) -> None:
    with pytest.raises(ActionFailedError, match="OOPS"):
        await amule._call(Op.GET_LOG)
    dead = ECClient("127.0.0.1", 1, "x", timeout=2)
    with pytest.raises(ECError):
        await AmuleClient(dead).stats()


async def test_reconnects_after_the_daemon_restarts(fake: FakeAmuled) -> None:
    port = fake.port  # type: ignore[attr-defined]
    client = AmuleClient(ECClient("127.0.0.1", port, "secret", timeout=5))
    await client.stats()
    # Drop the connection from the server side, like an amuled restart.
    assert client.ec._writer is not None
    client.ec._writer.transport.abort()
    await asyncio.sleep(0)
    with pytest.raises(ECError):
        await client.stats()
    stats, _ = await client.stats()  # a fresh connection
    assert stats.kad_nodes == 312
    await client.ec.close()


@pytest.mark.parametrize(
    "line",
    [
        "!2026-11-22 10:49:21: ERROR: WARNING Warning! You are running aMule as root.",
        "Assertion failed: ./src/unix/sockunix.cpp:DoEnableEvents:100: Assertion failed",
        "[3] wxOnAssert(char const*, int, char const*) in /lib/libwx_baseu-3.2.so.0",
        " 2026-11-22 11:09:20: 11:09:20: Error: Failed to modify descriptor 19 in epoll descriptor 17",
        "11:09:20: Debug: Failed to unregister 19 in direction 0",
    ],
)
def test_noise_is_filtered(line: str) -> None:
    assert is_noise(line)
    assert not is_noise("!2026-11-22 10:49:22: Connected to eMule Sunrise with LowID")
