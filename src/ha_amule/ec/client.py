"""Async connection to amuled's External Connections port.

aMule answers requests strictly in order, so one connection serves one request at a time;
a lock keeps concurrent callers from interleaving. The connection is opened lazily and
reopened after any error.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from ha_amule import __version__
from ha_amule.ec.codes import PROTOCOL_VERSION, Op, Tag
from ha_amule.ec.packet import HEADER, MAX_FRAME, ECPacket, ECTag, ProtocolError, decode_body

log = logging.getLogger(__name__)


class ECError(Exception):
    """amuled is unreachable or answered with an error."""


class ECAuthError(ECError):
    """amuled rejected the EC password."""


def password_hash(password: str, salt: int) -> bytes:
    """The salted response aMule expects: md5(md5hex(password) + md5hex("%X" % salt))."""
    pass_hex = hashlib.md5(password.encode(), usedforsecurity=False).hexdigest()
    salt_hex = hashlib.md5(f"{salt:X}".encode(), usedforsecurity=False).hexdigest()
    return hashlib.md5((pass_hex + salt_hex).encode(), usedforsecurity=False).digest()


class ECClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 15) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.server_version: str | None = None

    async def request(self, packet: ECPacket) -> ECPacket:
        async with self._lock:
            try:
                if self._writer is None:
                    await self._connect()
                return await self._roundtrip(packet)
            except ECAuthError:
                await self._close()
                raise
            except (OSError, TimeoutError, asyncio.IncompleteReadError, ProtocolError) as err:
                await self._close()
                raise ECError(f"{packet.describe()}: {err or type(err).__name__}") from err

    async def close(self) -> None:
        async with self._lock:
            await self._close()

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), self._timeout
        )
        reply = await self._roundtrip(
            ECPacket(
                Op.AUTH_REQ,
                [
                    ECTag.string(Tag.CLIENT_NAME, "ha-amule"),
                    ECTag.string(Tag.CLIENT_VERSION, __version__),
                    ECTag.uint(Tag.PROTOCOL_VERSION, PROTOCOL_VERSION),
                ],
            )
        )
        salt = reply.first(Tag.PASSWD_SALT)
        if reply.op != Op.AUTH_SALT or salt is None or not isinstance(salt.value, int):
            raise ECAuthError(_reason(reply, "amuled refused the connection"))
        reply = await self._roundtrip(
            ECPacket(Op.AUTH_PASSWD, [ECTag.hash16(Tag.PASSWD_HASH, password_hash(self._password, salt.value))])
        )
        if reply.op != Op.AUTH_OK:
            raise ECAuthError(_reason(reply, "Wrong EC password"))
        version = reply.first(Tag.SERVER_VERSION)
        self.server_version = str(version.value) if version else None
        log.debug("Connected to amuled %s", self.server_version)

    async def _roundtrip(self, packet: ECPacket) -> ECPacket:
        if self._reader is None or self._writer is None:
            raise ProtocolError("not connected")
        self._writer.write(packet.encode())
        await asyncio.wait_for(self._writer.drain(), self._timeout)
        header = await asyncio.wait_for(self._reader.readexactly(HEADER.size), self._timeout)
        flags, length = HEADER.unpack(header)
        if length > MAX_FRAME:
            raise ProtocolError(f"frame of {length} bytes")
        body = await asyncio.wait_for(self._reader.readexactly(length), self._timeout)
        return decode_body(flags, body)

    async def _close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def _reason(packet: ECPacket, default: str) -> str:
    strings = packet.strings()
    return strings[0] if strings else default
