"""High-level aMule operations on top of the EC client, returning plain models."""

from __future__ import annotations

import re
import time
from collections import deque
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel

from ha_amule.ec import codes
from ha_amule.ec.client import ECClient, ECError
from ha_amule.ec.codes import DetailLevel, Op, SearchType, Tag
from ha_amule.ec.packet import ECPacket, ECTag

HIGH_ID_THRESHOLD = 0x1000000  # ed2k IDs below this are "low IDs" (firewalled)
LOG_LINES = 500
SEARCH_GRACE = 5.0  # seconds a new search counts as running before aMule reports progress


class PartStatus(IntEnum):
    """PS_* in aMule's PartFile.h."""

    READY = 0
    EMPTY = 1
    WAITING_FOR_HASH = 2
    HASHING = 3
    ERROR = 4
    INSUFFICIENT = 5
    UNKNOWN = 6
    PAUSED = 7
    COMPLETING = 8
    COMPLETE = 9
    ALLOCATING = 10


Priority = Literal["low", "normal", "high", "auto"]
_PRIORITY_CODES: dict[str, int] = {"low": 0, "normal": 1, "high": 2, "auto": 5}
_PRIORITY_NAMES = {0: "low", 1: "normal", 2: "high", 3: "high", 4: "low"}

DownloadState = Literal["downloading", "waiting", "paused", "stopped", "hashing", "completing", "completed", "error"]
SearchScope = Literal["global", "local", "kad"]
FileType = Literal["", "Any", "Arc", "Audio", "Iso", "Doc", "Image", "Pro", "Video"]


class ActionFailedError(ECError):
    """amuled understood the request but refused it (bad link, unknown file...)."""


class ServerInfo(BaseModel):
    address: str
    name: str
    description: str = ""
    version: str = ""
    users: int = 0
    max_users: int = 0
    files: int = 0
    ping: int = 0
    failed: int = 0
    static: bool = False


class Connection(BaseModel):
    ed2k_connected: bool
    ed2k_connecting: bool
    ed2k_high_id: bool
    ed2k_id: int | None
    server: ServerInfo | None
    kad_running: bool
    kad_connected: bool
    kad_firewalled: bool


class Stats(BaseModel):
    download_speed: int  # bytes/s
    upload_speed: int
    download_limit: int  # bytes/s, 0 = unlimited
    upload_limit: int
    upload_queue: int
    sources: int
    banned: int
    ed2k_users: int
    ed2k_files: int
    kad_users: int
    kad_files: int
    kad_nodes: int
    total_received: int  # bytes since amuled started
    total_sent: int
    shared_files: int


class Download(BaseModel):
    id: int  # aMule's ECID, stable while amuled runs
    hash: str
    name: str
    size: int
    done: int
    transferred: int
    progress: float  # 0-100
    speed: int  # bytes/s
    state: DownloadState
    priority: Priority
    auto_priority: bool
    sources: int
    sources_transferring: int
    sources_a4af: int
    last_complete: int | None  # unix time a complete source was last seen
    last_received: int | None
    link: str
    category: int


class Upload(BaseModel):
    id: int
    user: str
    client: str
    file: str
    speed: int
    session: int
    total: int


class SharedFile(BaseModel):
    id: int
    hash: str
    name: str
    path: str
    size: int
    requests: int
    accepted: int
    transferred: int
    transferred_all: int
    priority: Priority
    complete_sources: int
    link: str


class SearchResult(BaseModel):
    id: int
    hash: str
    name: str
    size: int
    sources: int
    complete_sources: int
    known: Literal["new", "downloading", "downloaded", "cancelled"]
    rating: int = 0


class SearchStatus(BaseModel):
    running: bool
    progress: int  # 0-100 while running
    results: list[SearchResult]


class AmuleClient:
    def __init__(self, ec: ECClient) -> None:
        self.ec = ec
        self.log: deque[str] = deque(maxlen=LOG_LINES)
        self._search_started = 0.0

    # -- plumbing --------------------------------------------------------------------------

    async def _call(self, op: Op, *tags: ECTag) -> ECPacket:
        reply = await self.ec.request(ECPacket(op, list(tags)))
        if reply.op in (Op.FAILED, Op.AUTH_FAIL):
            raise ActionFailedError("; ".join(reply.strings()) or f"{op.name} failed")
        return reply

    @staticmethod
    def _detail(level: DetailLevel) -> ECTag:
        return ECTag.uint(Tag.DETAIL_LEVEL, level)

    # -- status ------------------------------------------------------------------------------

    async def stats(self) -> tuple[Stats, Connection]:
        reply = await self._call(Op.STAT_REQ, self._detail(DetailLevel.FULL))
        self._collect_log(reply)
        values = {t.name: t.value for t in reply.tags}

        def num(tag: Tag) -> int:
            value = values.get(tag)
            return value if isinstance(value, int) else 0

        stats = Stats(
            download_speed=num(Tag.STATS_DL_SPEED),
            upload_speed=num(Tag.STATS_UL_SPEED),
            download_limit=num(Tag.STATS_DL_SPEED_LIMIT),
            upload_limit=num(Tag.STATS_UL_SPEED_LIMIT),
            upload_queue=num(Tag.STATS_UL_QUEUE_LEN),
            sources=num(Tag.STATS_TOTAL_SRC_COUNT),
            banned=num(Tag.STATS_BANNED_COUNT),
            ed2k_users=num(Tag.STATS_ED2K_USERS),
            ed2k_files=num(Tag.STATS_ED2K_FILES),
            kad_users=num(Tag.STATS_KAD_USERS),
            kad_files=num(Tag.STATS_KAD_FILES),
            kad_nodes=num(Tag.STATS_KAD_NODES),
            total_received=num(Tag.STATS_TOTAL_RECEIVED_BYTES),
            total_sent=num(Tag.STATS_TOTAL_SENT_BYTES),
            shared_files=num(Tag.STATS_SHARED_FILE_COUNT),
        )
        state = reply.first(Tag.CONNSTATE)
        return stats, _connection(state)

    def _collect_log(self, reply: ECPacket) -> None:
        logger = reply.first(Tag.STATS_LOGGER_MESSAGE)
        if logger is None:
            return
        for line in logger.children:
            text = str(line.value).rstrip("\n")
            if text and not is_noise(text):
                self.log.append(text)

    # -- downloads ---------------------------------------------------------------------------

    async def downloads(self) -> list[Download]:
        reply = await self._call(Op.GET_DLOAD_QUEUE, self._detail(DetailLevel.CMD))
        return [_download(t) for t in reply.all(Tag.PARTFILE)]

    async def add_links(self, links: list[str]) -> None:
        await self._call(Op.ADD_LINK, *(ECTag.string(Tag.STRING, link.strip()) for link in links))

    async def _file_op(self, op: Op, hashes: list[str], *extra: ECTag) -> None:
        await self._call(op, *(ECTag.hash16(Tag.PARTFILE, h, *extra) for h in hashes))

    async def pause(self, hashes: list[str]) -> None:
        await self._file_op(Op.PARTFILE_PAUSE, hashes)

    async def resume(self, hashes: list[str]) -> None:
        await self._file_op(Op.PARTFILE_RESUME, hashes)

    async def stop(self, hashes: list[str]) -> None:
        await self._file_op(Op.PARTFILE_STOP, hashes)

    async def cancel(self, hashes: list[str]) -> None:
        await self._file_op(Op.PARTFILE_DELETE, hashes)

    async def set_priority(self, hashes: list[str], priority: Priority) -> None:
        prio = ECTag.uint(Tag.PARTFILE_PRIO, _PRIORITY_CODES[priority])
        await self._file_op(Op.PARTFILE_PRIO_SET, hashes, prio)

    async def clear_completed(self) -> None:
        await self._call(Op.CLEAR_COMPLETED)

    # -- uploads and shared files ------------------------------------------------------------

    async def uploads(self) -> list[Upload]:
        reply = await self._call(Op.GET_ULOAD_QUEUE, self._detail(DetailLevel.CMD))
        return [
            Upload(
                id=_int(t.value),
                user=t.str_of(Tag.CLIENT_NAME),
                client=" ".join(
                    s for s in (_client_name(t.int_of(Tag.CLIENT_SOFTWARE)), t.str_of(Tag.CLIENT_SOFT_VER_STR)) if s
                ),
                file=t.str_of(Tag.PARTFILE_NAME) or t.str_of(Tag.CLIENT_REMOTE_FILENAME),
                speed=t.int_of(Tag.CLIENT_UP_SPEED),
                session=t.int_of(Tag.CLIENT_UPLOAD_SESSION),
                total=t.int_of(Tag.CLIENT_UPLOAD_TOTAL),
            )
            for t in reply.all(Tag.CLIENT)
        ]

    async def shared_files(self) -> list[SharedFile]:
        reply = await self._call(Op.GET_SHARED_FILES, self._detail(DetailLevel.CMD))
        result = []
        for t in reply.all(Tag.KNOWNFILE):
            prio = t.int_of(Tag.KNOWNFILE_PRIO)
            result.append(
                SharedFile(
                    id=_int(t.value),
                    hash=t.str_of(Tag.PARTFILE_HASH),
                    name=t.str_of(Tag.PARTFILE_NAME),
                    path=t.str_of(Tag.KNOWNFILE_FILENAME),
                    size=t.int_of(Tag.PARTFILE_SIZE_FULL),
                    requests=t.int_of(Tag.KNOWNFILE_REQ_COUNT),
                    accepted=t.int_of(Tag.KNOWNFILE_ACCEPT_COUNT),
                    transferred=t.int_of(Tag.KNOWNFILE_XFERRED),
                    transferred_all=t.int_of(Tag.KNOWNFILE_XFERRED_ALL),
                    priority="auto" if prio >= 10 else _PRIORITY_NAMES.get(prio, "normal"),
                    complete_sources=t.int_of(Tag.KNOWNFILE_COMPLETE_SOURCES),
                    link=t.str_of(Tag.PARTFILE_ED2K_LINK),
                )
            )
        return result

    async def reload_shared(self) -> None:
        await self._call(Op.SHAREDFILES_RELOAD)

    # -- search ------------------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        scope: SearchScope = "global",
        file_type: FileType = "",
        extension: str = "",
        min_size: int = 0,
        max_size: int = 0,
        availability: int = 0,
    ) -> None:
        search_type = {"global": SearchType.GLOBAL, "local": SearchType.LOCAL, "kad": SearchType.KAD}[scope]
        children = [
            ECTag.string(Tag.SEARCH_NAME, query),
            ECTag.string(Tag.SEARCH_FILE_TYPE, "" if file_type == "Any" else file_type),
        ]
        if extension:
            children.append(ECTag.string(Tag.SEARCH_EXTENSION, extension.lstrip(".")))
        if availability:
            children.append(ECTag.uint(Tag.SEARCH_AVAILABILITY, availability))
        if min_size:
            children.append(ECTag.uint(Tag.SEARCH_MIN_SIZE, min_size))
        if max_size:
            children.append(ECTag.uint(Tag.SEARCH_MAX_SIZE, max_size))
        await self._call(Op.SEARCH_START, ECTag.uint(Tag.SEARCH_TYPE, search_type, *children))
        self._search_started = time.monotonic()

    async def search_status(self) -> SearchStatus:
        progress = await self._call(Op.SEARCH_PROGRESS)
        value = progress.first(Tag.SEARCH_STATUS)
        percent = _int(value.value) if value else 0
        reply = await self._call(Op.SEARCH_RESULTS, self._detail(DetailLevel.CMD))
        results = [
            SearchResult(
                id=_int(t.value),
                hash=t.str_of(Tag.PARTFILE_HASH),
                name=t.str_of(Tag.PARTFILE_NAME),
                size=t.int_of(Tag.PARTFILE_SIZE_FULL),
                sources=t.int_of(Tag.PARTFILE_SOURCE_COUNT),
                complete_sources=t.int_of(Tag.PARTFILE_SOURCE_COUNT_XFER),
                known=_SEARCH_KNOWN.get(t.int_of(Tag.PARTFILE_STATUS), "new"),
                rating=t.int_of(Tag.KNOWNFILE_RATING),
            )
            for t in reply.all(Tag.SEARCHFILE)
            if t.child(Tag.SEARCH_PARENT) is None  # duplicates aMule groups under a parent
        ]
        # aMule reports 0 both before a search starts reporting and once it is done.
        running = 0 < percent < 100 or (percent == 0 and time.monotonic() - self._search_started < SEARCH_GRACE)
        return SearchStatus(running=running, progress=percent if running else 0, results=results)

    async def stop_search(self) -> None:
        await self._call(Op.SEARCH_STOP)
        self._search_started = 0.0

    async def download_results(self, hashes: list[str], category: int = 0) -> None:
        await self._file_op(Op.DOWNLOAD_SEARCH_RESULT, hashes, ECTag.uint(Tag.PARTFILE_CAT, category))

    # -- networks ----------------------------------------------------------------------------

    async def servers(self) -> list[ServerInfo]:
        reply = await self._call(Op.GET_SERVER_LIST, self._detail(DetailLevel.FULL))
        return [_server(t) for t in reply.all(Tag.SERVER)]

    async def connect_ed2k(self, address: str | None = None) -> None:
        tags = []
        if address:
            host, _, port = address.rpartition(":")
            tags.append(ECTag.ipv4(Tag.SERVER, host, int(port)))
        await self._call(Op.SERVER_CONNECT, *tags)

    async def disconnect_ed2k(self) -> None:
        await self._call(Op.SERVER_DISCONNECT)

    async def start_kad(self) -> None:
        await self._call(Op.KAD_START)

    async def stop_kad(self) -> None:
        await self._call(Op.KAD_STOP)

    async def update_servers(self, url: str) -> None:
        await self._call(Op.SERVER_UPDATE_FROM_URL, ECTag.string(Tag.STRING, url))

    async def update_kad_nodes(self, url: str) -> None:
        await self._call(Op.KAD_UPDATE_FROM_URL, ECTag.string(Tag.STRING, url))

    async def set_limits(self, download_kbps: int | None = None, upload_kbps: int | None = None) -> None:
        """Speed limits in kB/s (0 = unlimited). Lasts until amuled restarts."""
        children = []
        if download_kbps is not None:
            children.append(ECTag.uint(Tag.CONN_MAX_DL, download_kbps))
        if upload_kbps is not None:
            children.append(ECTag.uint(Tag.CONN_MAX_UL, upload_kbps))
        if children:
            await self._call(Op.SET_PREFERENCES, ECTag(Tag.PREFS_CONNECTIONS, codes.TagType.CUSTOM, b"", children))


# -- decoding helpers ---------------------------------------------------------------------------

_SEARCH_KNOWN: dict[int, Literal["new", "downloading", "downloaded", "cancelled"]] = {
    0: "new",
    1: "downloaded",
    2: "downloading",
    3: "cancelled",
    4: "cancelled",
}

# aMule's client software ids (SO_* in ClientSoftware.h), for the uploads list.
_CLIENTS = {
    0: "eMule",
    1: "cDonkey",
    2: "xMule",
    3: "aMule",
    4: "Shareaza",
    5: "eMule+",
    6: "Hydranode",
    10: "MLDonkey",
    20: "lphant",
    21: "eMule Plus",
    22: "Hydranode",
    23: "Trustyfiles",
    40: "eDonkeyHybrid",
    50: "eDonkey",
    51: "Old eMule",
    52: "eD2k client",
}

# Lines amuled logs on every start that are not problems: the root warning (an add-on runs as
# root by design) and wxWidgets 3.2 debug noise (an assertion with a backtrace, epoll chatter).
_NOISE = re.compile(
    r"running aMule as root|security reasons|as an normal|^\W*user instead|^-{10,}|^\s*$"
    r"|Assertion failed|Backtrace follows|^\[\d+\] |addr2line|cannot read address information"
    r"|DoEnableEvents|descriptor \S+ (?:to|in) epoll|Debug: "
)


def is_noise(line: str) -> bool:
    return bool(_NOISE.search(line))


def _client_name(soft: int) -> str:
    return _CLIENTS.get(soft, "")


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _server(tag: ECTag) -> ServerInfo:
    return ServerInfo(
        address=str(tag.value),
        name=tag.str_of(Tag.SERVER_NAME) or str(tag.value),
        description=tag.str_of(Tag.SERVER_DESC),
        version=tag.str_of(Tag.SERVER_VERSION),
        users=tag.int_of(Tag.SERVER_USERS),
        max_users=tag.int_of(Tag.SERVER_USERS_MAX),
        files=tag.int_of(Tag.SERVER_FILES),
        ping=tag.int_of(Tag.SERVER_PING),
        failed=tag.int_of(Tag.SERVER_FAILED),
        static=bool(tag.int_of(Tag.SERVER_STATIC)),
    )


def _connection(state: ECTag | None) -> Connection:
    bits = _int(state.value) if state else 0
    ed2k = bool(bits & codes.CONN_ED2K)
    ed2k_id = state.int_of(Tag.ED2K_ID) if state and ed2k else None
    server = state.child(Tag.SERVER) if state else None
    return Connection(
        ed2k_connected=ed2k,
        ed2k_connecting=bool(bits & codes.CONN_ED2K_CONNECTING),
        ed2k_high_id=ed2k_id is not None and ed2k_id >= HIGH_ID_THRESHOLD,
        ed2k_id=ed2k_id,
        server=_server(server) if server else None,
        kad_running=bool(bits & codes.CONN_KAD_RUNNING),
        kad_connected=bool(bits & codes.CONN_KAD),
        kad_firewalled=bool(bits & codes.CONN_KAD_FIREWALLED),
    )


def _download_state(tag: ECTag) -> DownloadState:
    status = tag.int_of(Tag.PARTFILE_STATUS)
    if tag.int_of(Tag.PARTFILE_STOPPED):
        return "stopped"
    match status:
        case PartStatus.PAUSED:
            return "paused"
        case PartStatus.COMPLETE:
            return "completed"
        case PartStatus.COMPLETING:
            return "completing"
        case PartStatus.HASHING | PartStatus.WAITING_FOR_HASH | PartStatus.ALLOCATING:
            return "hashing"
        case PartStatus.ERROR | PartStatus.INSUFFICIENT:
            return "error"
    if tag.int_of(Tag.PARTFILE_SOURCE_COUNT_XFER) > 0 or tag.int_of(Tag.PARTFILE_SPEED) > 0:
        return "downloading"
    return "waiting"


def _download(tag: ECTag) -> Download:
    size = tag.int_of(Tag.PARTFILE_SIZE_FULL)
    done = tag.int_of(Tag.PARTFILE_SIZE_DONE)
    state = _download_state(tag)
    prio = tag.int_of(Tag.PARTFILE_PRIO)
    sources = tag.int_of(Tag.PARTFILE_SOURCE_COUNT)
    return Download(
        id=_int(tag.value),
        hash=tag.str_of(Tag.PARTFILE_HASH),
        name=tag.str_of(Tag.PARTFILE_NAME),
        size=size,
        done=size if state == "completed" else done,
        transferred=tag.int_of(Tag.PARTFILE_SIZE_XFER),
        progress=100.0 if state == "completed" else round(100 * done / size, 2) if size else 0.0,
        speed=tag.int_of(Tag.PARTFILE_SPEED),
        state=state,
        priority=_PRIORITY_NAMES.get(prio % 10, "normal"),
        auto_priority=prio >= 10,
        sources=sources,
        sources_transferring=tag.int_of(Tag.PARTFILE_SOURCE_COUNT_XFER),
        sources_a4af=tag.int_of(Tag.PARTFILE_SOURCE_COUNT_A4AF),
        last_complete=tag.int_of(Tag.PARTFILE_LAST_SEEN_COMP) or None,
        last_received=tag.int_of(Tag.PARTFILE_LAST_RECV) or None,
        link=tag.str_of(Tag.PARTFILE_ED2K_LINK),
        category=tag.int_of(Tag.PARTFILE_CAT),
    )
