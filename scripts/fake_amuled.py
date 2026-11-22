"""A stand-in for amuled's EC port with canned data, for `make demo` and the tests.

It speaks the real wire protocol (through ha_amule.ec.packet), checks the salted password,
and keeps just enough state that pausing, cancelling or downloading changes what it reports.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import struct
import sys
from dataclasses import dataclass, field

from ha_amule.ec.client import password_hash
from ha_amule.ec.codes import CONN_ED2K, CONN_KAD, CONN_KAD_RUNNING, Op, Tag, TagType
from ha_amule.ec.packet import HEADER, ECPacket, ECTag, decode_body

SALT = 0x1234ABCD5678
PS_EMPTY, PS_PAUSED, PS_COMPLETE = 1, 7, 9


def _hash(name: str) -> str:
    return hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()


@dataclass
class FakeFile:
    name: str
    size: int
    done: int = 0
    speed: int = 0
    status: int = PS_EMPTY
    sources: int = 0
    xfer: int = 0
    prio: int = 11  # auto, currently normal
    id: int = 0
    hash: str = ""

    def __post_init__(self) -> None:
        self.hash = self.hash or _hash(self.name)


@dataclass
class FakeAmuled:
    password: str = "demo"  # noqa: S105
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(100))
    downloads: list[FakeFile] = field(default_factory=list)
    results: list[FakeFile] = field(default_factory=list)
    search_progress: int = 0
    ed2k: bool = True
    kad: bool = True
    limits: tuple[int, int] = (0, 0)
    requests: list[ECPacket] = field(default_factory=list)
    log: list[str] = field(default_factory=lambda: [" 2026-11-22 10:00:00: aMuleD 2.3.3 (fake) started\n"])

    def __post_init__(self) -> None:
        if not self.downloads:
            for f in (
                FakeFile("debian-13.2.0-amd64-netinst.iso", 790_626_304, 512_000_000, 412_000, sources=24, xfer=6),
                FakeFile("Big Buck Bunny (2008) 1080p.mkv", 928_670_754, 120_000_000, 96_000, sources=9, xfer=2),
                FakeFile("Sintel.2010.4k.mkv", 4_404_019_200, 0, 0, sources=3, xfer=0),
                FakeFile("LibreOffice_25.8.2_Linux_x86-64_deb.tar.gz", 223_340_544, 77_000_000, 0, PS_PAUSED, 5),
                FakeFile("ubuntu-24.04.3-desktop-amd64.iso", 6_345_887_744, 6_345_887_744, 0, PS_COMPLETE),
            ):
                f.id = next(self.ids)
                self.downloads.append(f)

    # -- server ------------------------------------------------------------------------------

    async def serve(self, host: str = "127.0.0.1", port: int = 0) -> asyncio.Server:
        return await asyncio.start_server(self._client, host, port)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        authed = False
        try:
            while True:
                flags, length = HEADER.unpack(await reader.readexactly(HEADER.size))
                request = decode_body(flags, await reader.readexactly(length))
                self.requests.append(request)
                if request.op == Op.AUTH_REQ:
                    reply = ECPacket(Op.AUTH_SALT, [ECTag.uint(Tag.PASSWD_SALT, SALT)])
                elif request.op == Op.AUTH_PASSWD:
                    given = request.first(Tag.PASSWD_HASH)
                    authed = given is not None and given.data == password_hash(self.password, SALT)
                    reply = (
                        ECPacket(Op.AUTH_OK, [ECTag.string(Tag.SERVER_VERSION, "2.3.3")])
                        if authed
                        else ECPacket(Op.AUTH_FAIL, [ECTag.string(Tag.STRING, "Authentication failed.")])
                    )
                elif not authed:
                    reply = ECPacket(Op.AUTH_FAIL, [ECTag.string(Tag.STRING, "Please authenticate first.")])
                else:
                    reply = self.handle(request)
                writer.write(reply.encode())
                await writer.drain()
                if reply.op == Op.AUTH_FAIL:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    # -- requests ----------------------------------------------------------------------------

    def handle(self, req: ECPacket) -> ECPacket:  # noqa: PLR0912
        op = req.op
        if op == Op.STAT_REQ:
            return ECPacket(Op.STATS, [*self._stats(), self._connstate()])
        if op == Op.GET_CONNSTATE:
            return ECPacket(Op.MISC_DATA, [self._connstate()])
        if op == Op.GET_DLOAD_QUEUE:
            return ECPacket(Op.DLOAD_QUEUE, [self._partfile(f) for f in self.downloads])
        if op == Op.ADD_LINK:
            for tag in req.all(Tag.STRING):
                parts = str(tag.value).split("|")
                if len(parts) < 5 or parts[1] != "file" or any(f.hash == parts[4].lower() for f in self.downloads):
                    return self._failed("Invalid link or already on list.")
                self.downloads.append(FakeFile(parts[2], int(parts[3]), id=next(self.ids), hash=parts[4].lower()))
            return ECPacket(Op.NOOP)
        if op in (Op.PARTFILE_PAUSE, Op.PARTFILE_RESUME, Op.PARTFILE_STOP, Op.PARTFILE_DELETE, Op.PARTFILE_PRIO_SET):
            for tag in req.all(Tag.PARTFILE):
                f = next((d for d in self.downloads if d.hash == tag.data.hex()), None)
                if f is None:
                    return self._failed(f"FileHash not found: {tag.data.hex().upper()}")
                if op in (Op.PARTFILE_PAUSE, Op.PARTFILE_STOP):
                    f.status, f.speed, f.xfer = PS_PAUSED, 0, 0
                elif op == Op.PARTFILE_RESUME:
                    f.status = PS_EMPTY
                elif op == Op.PARTFILE_PRIO_SET:
                    value = tag.children[0].value if tag.children else 1
                    f.prio = 11 if value == 5 else int(value)  # type: ignore[arg-type]
                else:
                    self.downloads.remove(f)
            return ECPacket(Op.NOOP)
        if op == Op.CLEAR_COMPLETED:
            self.downloads = [f for f in self.downloads if f.status != PS_COMPLETE]
            return ECPacket(Op.NOOP)
        if op == Op.SEARCH_START:
            query = req.tags[0].str_of(Tag.SEARCH_NAME) if req.tags else ""
            self.results = [
                FakeFile(f"{query} {suffix}", size, sources=src, xfer=complete, id=next(self.ids))
                for suffix, size, src, complete in (
                    ("- Complete Collection.zip", 1_288_490_188, 41, 30),
                    ("(Remastered) [FLAC].rar", 512_000_000, 12, 9),
                    ("1080p WEB-DL.mkv", 2_147_483_648, 87, 64),
                    ("sample.avi", 15_000_000, 2, 1),
                )
            ]
            self.search_progress = 1
            return ECPacket(Op.STRINGS, [ECTag.string(Tag.STRING, "Search in progress. Refetch results in a moment!")])
        if op == Op.SEARCH_PROGRESS:
            if self.search_progress:
                self.search_progress += 35
                if self.search_progress >= 100:
                    self.search_progress = 0
            return ECPacket(Op.SEARCH_PROGRESS, [ECTag.uint(Tag.SEARCH_STATUS, self.search_progress)])
        if op == Op.SEARCH_RESULTS:
            shown = self.results if not self.search_progress or self.search_progress > 50 else self.results[:2]
            return ECPacket(Op.SEARCH_RESULTS, [self._searchfile(f) for f in shown])
        if op == Op.SEARCH_STOP:
            self.search_progress = 0
            return ECPacket(Op.MISC_DATA)
        if op == Op.DOWNLOAD_SEARCH_RESULT:
            for tag in req.all(Tag.PARTFILE):
                match = next((r for r in self.results if r.hash == tag.data.hex()), None)
                if match and all(d.hash != match.hash for d in self.downloads):
                    self.downloads.append(FakeFile(match.name, match.size, id=next(self.ids), sources=match.sources))
            return ECPacket(Op.STRINGS)
        if op == Op.GET_SERVER_LIST:
            return ECPacket(Op.SERVER_LIST, self._servers())
        if op in (Op.SERVER_CONNECT, Op.SERVER_DISCONNECT):
            self.ed2k = op == Op.SERVER_CONNECT
            return ECPacket(Op.NOOP)
        if op in (Op.KAD_START, Op.KAD_STOP):
            self.kad = op == Op.KAD_START
            return ECPacket(Op.NOOP)
        if op == Op.GET_ULOAD_QUEUE:
            return ECPacket(Op.ULOAD_QUEUE, [self._upload()])
        if op == Op.GET_SHARED_FILES:
            return ECPacket(Op.SHARED_FILES, [self._shared(f) for f in self.downloads if f.status == PS_COMPLETE])
        if op == Op.SET_PREFERENCES:
            conn = req.first(Tag.PREFS_CONNECTIONS)
            if conn:
                self.limits = (
                    conn.int_of(Tag.CONN_MAX_DL, self.limits[0]),
                    conn.int_of(Tag.CONN_MAX_UL, self.limits[1]),
                )
            return ECPacket(Op.NOOP)
        if op in (Op.SHAREDFILES_RELOAD, Op.KAD_UPDATE_FROM_URL, Op.SERVER_UPDATE_FROM_URL):
            return ECPacket(Op.NOOP)
        return self._failed("OOPS! OpCode processing error!")

    @staticmethod
    def _failed(message: str) -> ECPacket:
        return ECPacket(Op.FAILED, [ECTag.string(Tag.STRING, message)])

    def _stats(self) -> list[ECTag]:
        log = ECTag(
            Tag.STATS_LOGGER_MESSAGE, TagType.CUSTOM, b"", [ECTag.string(Tag.STRING, line) for line in self.log]
        )
        self.log = []
        down = sum(f.speed for f in self.downloads if f.status == PS_EMPTY)
        return [
            log,
            ECTag.uint(Tag.STATS_TOTAL_SENT_BYTES, 1_234_567_890),
            ECTag.uint(Tag.STATS_TOTAL_RECEIVED_BYTES, 9_876_543_210),
            ECTag.uint(Tag.STATS_SHARED_FILE_COUNT, sum(f.status == PS_COMPLETE for f in self.downloads)),
            ECTag.uint(Tag.STATS_UL_SPEED, 38_000),
            ECTag.uint(Tag.STATS_DL_SPEED, down),
            ECTag.uint(Tag.STATS_UL_SPEED_LIMIT, self.limits[1] * 1024),
            ECTag.uint(Tag.STATS_DL_SPEED_LIMIT, self.limits[0] * 1024),
            ECTag.uint(Tag.STATS_UL_QUEUE_LEN, 17),
            ECTag.uint(Tag.STATS_TOTAL_SRC_COUNT, sum(f.sources for f in self.downloads)),
            ECTag.uint(Tag.STATS_ED2K_USERS, 164_666 if self.ed2k else 0),
            ECTag.uint(Tag.STATS_KAD_USERS, 1_250_000 if self.kad else 0),
            ECTag.uint(Tag.STATS_ED2K_FILES, 172_642_692 if self.ed2k else 0),
            ECTag.uint(Tag.STATS_KAD_FILES, 98_000_000 if self.kad else 0),
            ECTag.uint(Tag.STATS_KAD_NODES, 312 if self.kad else 0),
        ]

    def _connstate(self) -> ECTag:
        bits = (CONN_ED2K if self.ed2k else 0) | ((CONN_KAD | CONN_KAD_RUNNING) if self.kad else 0)
        children = []
        if self.ed2k:
            children += [self._servers()[0], ECTag.uint(Tag.ED2K_ID, 2_130_706_433)]
        children.append(ECTag.uint(Tag.CLIENT_ID, 2_130_706_433))
        return ECTag.uint(Tag.CONNSTATE, bits, *children)

    def _servers(self) -> list[ECTag]:
        return [
            ECTag(
                Tag.SERVER,
                TagType.IPV4,
                bytes([176, 123, 5, 89]) + struct.pack(">H", 4725),
                [
                    ECTag.string(Tag.SERVER_NAME, "eMule Sunrise"),
                    ECTag.string(Tag.SERVER_DESC, "Not perfect, but real"),
                    ECTag.uint(Tag.SERVER_USERS, 54_910),
                    ECTag.uint(Tag.SERVER_USERS_MAX, 55_000),
                    ECTag.uint(Tag.SERVER_FILES, 24_213_845),
                    ECTag.uint(Tag.SERVER_PING, 137),
                ],
            ),
            ECTag(
                Tag.SERVER,
                TagType.IPV4,
                bytes([176, 125, 242, 230]) + struct.pack(">H", 5555),
                [
                    ECTag.string(Tag.SERVER_NAME, "eNode"),
                    ECTag.string(Tag.SERVER_DESC, "Over 150 mio files!"),
                    ECTag.uint(Tag.SERVER_USERS, 29_695),
                    ECTag.uint(Tag.SERVER_FILES, 58_825_586),
                    ECTag.uint(Tag.SERVER_PING, 98),
                ],
            ),
        ]

    @staticmethod
    def _partfile(f: FakeFile) -> ECTag:
        return ECTag.uint(
            Tag.PARTFILE,
            f.id,
            ECTag.string(Tag.PARTFILE_NAME, f.name),
            ECTag.hash16(Tag.PARTFILE_HASH, f.hash),
            ECTag.uint(Tag.PARTFILE_SIZE_FULL, f.size),
            ECTag.string(Tag.PARTFILE_ED2K_LINK, f"ed2k://|file|{f.name}|{f.size}|{f.hash.upper()}|/"),
            ECTag.uint(Tag.PARTFILE_STATUS, f.status),
            ECTag.uint(Tag.PARTFILE_STOPPED, 0),
            ECTag.uint(Tag.PARTFILE_SOURCE_COUNT, f.sources),
            ECTag.uint(Tag.PARTFILE_SOURCE_COUNT_XFER, f.xfer if f.status == PS_EMPTY else 0),
            ECTag.uint(Tag.PARTFILE_SIZE_XFER, f.done),
            ECTag.uint(Tag.PARTFILE_SIZE_DONE, f.done),
            ECTag.uint(Tag.PARTFILE_SPEED, f.speed if f.status == PS_EMPTY else 0),
            ECTag.uint(Tag.PARTFILE_PRIO, f.prio),
            ECTag.uint(Tag.PARTFILE_CAT, 0),
            ECTag.uint(Tag.PARTFILE_LAST_SEEN_COMP, 1_795_344_655),
        )

    @staticmethod
    def _searchfile(f: FakeFile) -> ECTag:
        return ECTag.uint(
            Tag.SEARCHFILE,
            f.id,
            ECTag.uint(Tag.PARTFILE_SOURCE_COUNT, f.sources),
            ECTag.uint(Tag.PARTFILE_SOURCE_COUNT_XFER, f.xfer),
            ECTag.uint(Tag.PARTFILE_STATUS, 0),
            ECTag.string(Tag.PARTFILE_NAME, f.name),
            ECTag.uint(Tag.PARTFILE_SIZE_FULL, f.size),
            ECTag.hash16(Tag.PARTFILE_HASH, f.hash),
        )

    @staticmethod
    def _upload() -> ECTag:
        return ECTag.uint(
            Tag.CLIENT,
            7,
            ECTag.string(Tag.CLIENT_NAME, "http://www.aMule.org"),
            ECTag.uint(Tag.CLIENT_SOFTWARE, 3),
            ECTag.string(Tag.CLIENT_SOFT_VER_STR, "2.3.3"),
            ECTag.uint(Tag.CLIENT_UP_SPEED, 38_000),
            ECTag.uint(Tag.CLIENT_UPLOAD_SESSION, 3_500_000),
            ECTag.uint(Tag.CLIENT_UPLOAD_TOTAL, 9_000_000),
            ECTag.string(Tag.PARTFILE_NAME, "ubuntu-24.04.3-desktop-amd64.iso"),
        )

    @staticmethod
    def _shared(f: FakeFile) -> ECTag:
        return ECTag.uint(
            Tag.KNOWNFILE,
            f.id,
            ECTag.uint(Tag.KNOWNFILE_REQ_COUNT, 12),
            ECTag.uint(Tag.KNOWNFILE_ACCEPT_COUNT, 4),
            ECTag.uint(Tag.KNOWNFILE_XFERRED, 50_000_000),
            ECTag.uint(Tag.KNOWNFILE_XFERRED_ALL, 3_000_000_000),
            ECTag.uint(Tag.KNOWNFILE_PRIO, 11),
            ECTag.uint(Tag.KNOWNFILE_COMPLETE_SOURCES, 40),
            ECTag.string(Tag.PARTFILE_NAME, f.name),
            ECTag.hash16(Tag.PARTFILE_HASH, f.hash),
            ECTag.string(Tag.KNOWNFILE_FILENAME, f"/share/amule/incoming/{f.name}"),
            ECTag.uint(Tag.PARTFILE_SIZE_FULL, f.size),
            ECTag.string(Tag.PARTFILE_ED2K_LINK, f"ed2k://|file|{f.name}|{f.size}|{f.hash.upper()}|/"),
        )


async def main(port: int) -> None:
    server = await FakeAmuled().serve(port=port)
    print(f"fake amuled listening on 127.0.0.1:{port} (password: demo)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 14713))
