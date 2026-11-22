"""Client for the aMule app's API, reached over the Supervisor network."""

from __future__ import annotations

import json
from typing import Any

import aiohttp


class AmuleError(Exception):
    """The app answered with an error."""


class AmuleConnectionError(AmuleError):
    """The app is not reachable."""


class AmuleAuthError(AmuleError):
    """The API key was rejected."""


class AmuleApi:
    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, api_key: str) -> None:
        self._session = session
        self._base = f"http://{host}:{port}/api"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._base}/{path}",
                json=payload,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (401, 403):
                    raise AmuleAuthError("The app rejected the API key")
                text = await response.text()
                body = json.loads(text) if text else {}
                if response.status >= 400:
                    raise AmuleError(_detail(body, f"HTTP {response.status}"))
                return body
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise AmuleConnectionError(str(err) or type(err).__name__) from err

    async def overview(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("GET", "overview")
        return result

    async def add_links(self, links: list[str]) -> None:
        await self._request("POST", "downloads", {"links": links})

    async def downloads_action(self, action: str, hashes: list[str]) -> None:
        await self._request("POST", f"downloads/{action}", {"hashes": hashes})

    async def clear_completed(self) -> None:
        await self._request("POST", "downloads/clear-completed")

    async def set_network(self, network: str, enabled: bool) -> None:
        await self._request("POST", f"network/{network}", {"enabled": enabled})

    async def set_limits(self, **limits: int) -> None:
        await self._request("POST", "limits", limits)


def _detail(body: Any, default: str) -> str:
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])
    return default
