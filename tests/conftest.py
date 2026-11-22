from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fake_amuled import FakeAmuled

from ha_amule.amule import AmuleClient
from ha_amule.ec.client import ECClient


@pytest.fixture
async def fake() -> AsyncIterator[FakeAmuled]:
    daemon = FakeAmuled(password="secret")
    server = await daemon.serve()
    daemon.port = server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]
    async with server:
        yield daemon
        server.close()


@pytest.fixture
async def amule(fake: FakeAmuled) -> AsyncIterator[AmuleClient]:
    client = AmuleClient(ECClient("127.0.0.1", fake.port, "secret", timeout=5))  # type: ignore[attr-defined]
    yield client
    await client.ec.close()
