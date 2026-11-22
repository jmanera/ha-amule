"""HTTP API for the web UI and the Home Assistant integration, plus the UI itself.

The UI is served through Ingress with relative URLs only, so it works under Ingress'
`/api/hassio_ingress/<token>/` prefix. The integration reaches the app over the Supervisor's
network with a bearer key it got through discovery (see discovery.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ha_amule import __version__, discovery
from ha_amule.amule import (
    ActionFailedError,
    AmuleClient,
    Connection,
    Download,
    FileType,
    Priority,
    SearchScope,
    SearchStatus,
    ServerInfo,
    SharedFile,
    Stats,
    Upload,
)
from ha_amule.config import Settings
from ha_amule.daemon import Daemon, ec_password
from ha_amule.ec.client import ECAuthError, ECClient, ECError

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INGRESS_PROXY = "172.30.32.2"  # the Supervisor's Ingress gateway
ED2K_PREFIX = "ed2k://"


class Status(BaseModel):
    version: str
    amule_version: str | None
    connection: Connection
    error: str | None = None


class DownloadCounts(BaseModel):
    total: int
    downloading: int
    waiting: int
    paused: int
    completed: int
    error: int


class Overview(BaseModel):
    """Everything the integration polls, in one request."""

    status: Status
    stats: Stats
    counts: DownloadCounts
    downloads: list[Download]


class Links(BaseModel):
    links: list[str] = Field(min_length=1, max_length=200)

    @field_validator("links")
    @classmethod
    def ed2k_only(cls, links: list[str]) -> list[str]:
        cleaned = [link.strip() for link in links if link.strip()]
        if not cleaned:
            raise ValueError("No links given")
        bad = [link for link in cleaned if not link.lower().startswith(ED2K_PREFIX)]
        if bad:
            raise ValueError(f"Not an ed2k link: {bad[0][:80]}")
        return cleaned


class Hashes(BaseModel):
    hashes: list[str] = Field(min_length=1, max_length=500)

    @field_validator("hashes")
    @classmethod
    def valid(cls, hashes: list[str]) -> list[str]:
        for h in hashes:
            if len(h) != 32 or any(c not in "0123456789abcdefABCDEF" for c in h):
                raise ValueError(f"Not a file hash: {h[:40]}")
        return hashes


class PriorityChange(Hashes):
    priority: Priority


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    scope: SearchScope = "global"
    file_type: FileType = ""
    extension: str = Field(default="", max_length=10, pattern=r"^\.?[A-Za-z0-9]*$")
    min_size: int = Field(default=0, ge=0)  # bytes
    max_size: int = Field(default=0, ge=0)
    availability: int = Field(default=0, ge=0)


class Limits(BaseModel):
    download_kbps: int | None = Field(default=None, ge=0, le=1_000_000)
    upload_kbps: int | None = Field(default=None, ge=0, le=1_000_000)


class Toggle(BaseModel):
    enabled: bool


class ServerConnect(BaseModel):
    address: str | None = Field(default=None, pattern=r"^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$")


def count(downloads: list[Download]) -> DownloadCounts:
    by_state = {s: sum(d.state == s for d in downloads) for s in ("downloading", "waiting", "paused", "completed")}
    return DownloadCounts(
        total=len(downloads),
        downloading=by_state["downloading"],
        waiting=by_state["waiting"],
        paused=by_state["paused"] + sum(d.state == "stopped" for d in downloads),
        completed=by_state["completed"],
        error=sum(d.state == "error" for d in downloads),
    )


def create_app(settings: Settings, client: AmuleClient | None = None) -> FastAPI:
    password = settings.ec_password or ec_password(settings)
    daemon = Daemon(settings, password) if settings.manage_daemon and client is None else None
    api_key = discovery.integration_key(settings.data_dir) if settings.ingress_only else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal client
        if daemon:
            daemon.start()
        if client is None:
            client = AmuleClient(ECClient(settings.ec_host or "127.0.0.1", settings.ec_port, password))
        app.state.client = client
        tasks: list[asyncio.Task[object]] = [asyncio.create_task(_bootstrap(settings, client))]
        if api_key:
            tasks.append(asyncio.create_task(discovery.announce(settings.http_port, api_key)))
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await client.ec.close()
        if daemon:
            await daemon.stop()

    app = FastAPI(title="aMule for Home Assistant", version=__version__, lifespan=lifespan)
    if client is not None:
        app.state.client = client

    if api_key:
        expected = f"Bearer {api_key}"

        @app.middleware("http")
        async def ingress_or_key(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            via_ingress = request.client is not None and request.client.host in (INGRESS_PROXY, "127.0.0.1")
            given = request.headers.get("authorization", "")
            if not via_ingress and not secrets.compare_digest(given, expected):
                return JSONResponse({"detail": "Open aMule from Home Assistant"}, 403)
            return await call_next(request)

    def amule(request: Request) -> AmuleClient:
        c: AmuleClient = request.app.state.client
        return c

    @app.exception_handler(ActionFailedError)
    async def refused(_: Request, exc: ActionFailedError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ECAuthError)
    async def auth_failed(_: Request, exc: ECAuthError) -> JSONResponse:
        return JSONResponse({"detail": f"aMule refused the connection: {exc}"}, status_code=502)

    @app.exception_handler(ECError)
    async def unavailable(_: Request, exc: ECError) -> JSONResponse:
        log.debug("EC request failed: %s", exc)
        detail = daemon.last_error if daemon and daemon.last_error else "aMule is starting"
        return JSONResponse({"detail": detail}, status_code=503)

    async def status(c: AmuleClient, connection: Connection) -> Status:
        return Status(
            version=__version__,
            amule_version=c.ec.server_version,
            connection=connection,
            error=daemon.last_error if daemon and not daemon.running else None,
        )

    @app.get("/api/overview")
    async def overview(request: Request) -> Overview:
        c = amule(request)
        stats, connection = await c.stats()
        downloads = await c.downloads()
        return Overview(
            status=await status(c, connection),
            stats=stats,
            counts=count(downloads),
            downloads=downloads,
        )

    # -- downloads --------------------------------------------------------------------------

    @app.get("/api/downloads")
    async def downloads(request: Request) -> list[Download]:
        return await amule(request).downloads()

    @app.post("/api/downloads", status_code=202)
    async def add_links(body: Links, request: Request) -> None:
        await amule(request).add_links(body.links)

    @app.post("/api/downloads/pause", status_code=204)
    async def pause(body: Hashes, request: Request) -> None:
        await amule(request).pause(body.hashes)

    @app.post("/api/downloads/resume", status_code=204)
    async def resume(body: Hashes, request: Request) -> None:
        await amule(request).resume(body.hashes)

    @app.post("/api/downloads/stop", status_code=204)
    async def stop(body: Hashes, request: Request) -> None:
        await amule(request).stop(body.hashes)

    @app.post("/api/downloads/cancel", status_code=204)
    async def cancel(body: Hashes, request: Request) -> None:
        await amule(request).cancel(body.hashes)

    @app.post("/api/downloads/priority", status_code=204)
    async def priority(body: PriorityChange, request: Request) -> None:
        await amule(request).set_priority(body.hashes, body.priority)

    @app.post("/api/downloads/clear-completed", status_code=204)
    async def clear_completed(request: Request) -> None:
        await amule(request).clear_completed()

    # -- search -----------------------------------------------------------------------------

    @app.post("/api/search", status_code=202)
    async def search(body: SearchRequest, request: Request) -> None:
        await amule(request).search(
            body.query.strip(),
            scope=body.scope,
            file_type=body.file_type,
            extension=body.extension,
            min_size=body.min_size,
            max_size=body.max_size,
            availability=body.availability,
        )

    @app.get("/api/search")
    async def search_status(request: Request) -> SearchStatus:
        return await amule(request).search_status()

    @app.delete("/api/search", status_code=204)
    async def stop_search(request: Request) -> None:
        await amule(request).stop_search()

    @app.post("/api/search/download", status_code=202)
    async def download_results(body: Hashes, request: Request) -> None:
        await amule(request).download_results(body.hashes)

    # -- uploads, shared files, networks ----------------------------------------------------

    @app.get("/api/uploads")
    async def uploads(request: Request) -> list[Upload]:
        return await amule(request).uploads()

    @app.get("/api/shared")
    async def shared(request: Request) -> list[SharedFile]:
        return await amule(request).shared_files()

    @app.post("/api/shared/reload", status_code=204)
    async def reload_shared(request: Request) -> None:
        await amule(request).reload_shared()

    @app.get("/api/servers")
    async def servers(request: Request) -> list[ServerInfo]:
        return await amule(request).servers()

    @app.post("/api/network/ed2k", status_code=204)
    async def ed2k(body: Toggle, request: Request) -> None:
        c = amule(request)
        await (c.connect_ed2k() if body.enabled else c.disconnect_ed2k())

    @app.post("/api/network/ed2k/connect", status_code=204)
    async def connect_server(body: ServerConnect, request: Request) -> None:
        await amule(request).connect_ed2k(body.address)

    @app.post("/api/network/kad", status_code=204)
    async def kad(body: Toggle, request: Request) -> None:
        c = amule(request)
        await (c.start_kad() if body.enabled else c.stop_kad())

    @app.post("/api/limits", status_code=204)
    async def limits(body: Limits, request: Request) -> None:
        await amule(request).set_limits(body.download_kbps, body.upload_kbps)

    @app.get("/api/log")
    async def get_log(request: Request) -> list[str]:
        c = amule(request)
        with contextlib.suppress(ECError):
            await c.stats()  # pulls new log lines
        return list(c.log)

    @app.get("/api/{path:path}", include_in_schema=False)
    async def api_not_found(path: str) -> None:
        raise HTTPException(404)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app


async def _bootstrap(settings: Settings, client: AmuleClient) -> None:
    """Fetch Kad nodes on the first start; amuled can't join Kad without any."""
    if not settings.connect_kad or not settings.nodes_url or not settings.manage_daemon:
        return
    if (settings.config_dir / "nodes.dat").is_file():
        return
    for _ in range(30):
        try:
            await client.update_kad_nodes(settings.nodes_url)
        except ECError:
            await asyncio.sleep(2)
            continue
        log.info("Requested Kad nodes from %s", settings.nodes_url)
        return
