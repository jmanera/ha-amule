"""Encoding and decoding of EC packets and tags.

Wire format (big-endian): a frame is `flags:u32 length:u32 body`. The body is
`opcode:u8 tag_count:u16 tag*`, and a tag is
`name<<1|has_children:u16 type:u8 length:u32 [child_count:u16 child*] data`, where `length`
covers the data plus every child (header included). With EC_FLAG_UTF8_NUMBERS the header
numbers (not the data) are UTF-8 encoded code points; with EC_FLAG_ZLIB the body is deflated.
This client never asks for either, but decodes both in case a daemon sends them.
"""

from __future__ import annotations

import ipaddress
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field

from ha_amule.ec.codes import Op, Tag, TagType

FLAG_BASE = 0x20  # always set
FLAG_ZLIB = 0x01
FLAG_UTF8_NUMBERS = 0x02
FLAG_LARGE_TAG_COUNT = 0x10
HEADER = struct.Struct(">II")
MAX_FRAME = 64 * 1024 * 1024


class ProtocolError(Exception):
    """The daemon sent something this client can't parse."""


@dataclass
class ECTag:
    name: int
    type: TagType
    data: bytes = b""
    children: list[ECTag] = field(default_factory=list)

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def uint(cls, name: int, value: int, *children: ECTag) -> ECTag:
        """An unsigned integer in the smallest type that holds it, like aMule does."""
        for tag_type, fmt in (
            (TagType.UINT8, ">B"),
            (TagType.UINT16, ">H"),
            (TagType.UINT32, ">I"),
            (TagType.UINT64, ">Q"),
        ):
            if value < 1 << (8 * struct.calcsize(fmt)):
                return cls(name, tag_type, struct.pack(fmt, value), list(children))
        raise ValueError(f"{value} does not fit in 64 bits")

    @classmethod
    def string(cls, name: int, value: str, *children: ECTag) -> ECTag:
        return cls(name, TagType.STRING, value.encode() + b"\0", list(children))

    @classmethod
    def hash16(cls, name: int, value: bytes | str, *children: ECTag) -> ECTag:
        raw = bytes.fromhex(value) if isinstance(value, str) else value
        if len(raw) != 16:
            raise ValueError("an MD4/MD5 hash has 16 bytes")
        return cls(name, TagType.HASH16, raw, list(children))

    @classmethod
    def ipv4(cls, name: int, address: str, port: int) -> ECTag:
        return cls(name, TagType.IPV4, ipaddress.IPv4Address(address).packed + struct.pack(">H", port))

    # -- reading --------------------------------------------------------------------------------

    @property
    def value(self) -> int | float | str | bytes | None:
        match self.type:
            case TagType.UINT8 | TagType.UINT16 | TagType.UINT32 | TagType.UINT64:
                return int.from_bytes(self.data, "big")
            case TagType.STRING:
                return self.data.rstrip(b"\0").decode(errors="replace")
            case TagType.DOUBLE:
                return float(self.data.rstrip(b"\0") or 0)
            case TagType.HASH16 | TagType.UINT128:
                return self.data.hex()
            case TagType.IPV4:
                ip = ipaddress.IPv4Address(self.data[:4])
                return f"{ip}:{int.from_bytes(self.data[4:6], 'big')}"
            case TagType.UNKNOWN if not self.data:
                return None
            case _:
                return self.data

    def child(self, name: int) -> ECTag | None:
        return next((c for c in self.children if c.name == name), None)

    def get(self, name: int, default: object = None) -> object:
        tag = self.child(name)
        return default if tag is None else tag.value

    def int_of(self, name: int, default: int = 0) -> int:
        value = self.get(name)
        return value if isinstance(value, int) else default

    def str_of(self, name: int, default: str = "") -> str:
        value = self.get(name)
        return value if isinstance(value, str) else default

    def encode(self) -> bytes:
        children = b"".join(c.encode() for c in self.children)
        head = struct.pack(">HBI", (self.name << 1) | bool(self.children), self.type, len(children) + len(self.data))
        if self.children:
            head += struct.pack(">H", len(self.children))
        return head + children + self.data


@dataclass
class ECPacket:
    op: int
    tags: list[ECTag] = field(default_factory=list)

    def __iter__(self) -> Iterator[ECTag]:
        return iter(self.tags)

    def first(self, name: int) -> ECTag | None:
        return next((t for t in self.tags if t.name == name), None)

    def all(self, name: int) -> list[ECTag]:
        return [t for t in self.tags if t.name == name]

    def strings(self) -> list[str]:
        return [str(t.value) for t in self.tags if t.name == Tag.STRING]

    def encode(self) -> bytes:
        body = struct.pack(">BH", self.op, len(self.tags)) + b"".join(t.encode() for t in self.tags)
        return HEADER.pack(FLAG_BASE, len(body)) + body

    def describe(self) -> str:
        try:
            return Op(self.op).name
        except ValueError:
            return f"0x{self.op:02x}"


class _Reader:
    def __init__(self, data: bytes, utf8_numbers: bool) -> None:
        self.data = data
        self.pos = 0
        self.utf8 = utf8_numbers

    def raw(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise ProtocolError("truncated packet")
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def number(self, size: int) -> int:
        if not self.utf8:
            return int.from_bytes(self.raw(size), "big")
        first = self.raw(1)[0]
        extra = (
            0
            if first < 0x80
            else 1
            if first < 0xE0
            else 2
            if first < 0xF0
            else 3
            if first < 0xF8
            else 4
            if first < 0xFC
            else 5
        )
        try:
            return ord((bytes([first]) + self.raw(extra)).decode("utf-8", "surrogatepass"))
        except (UnicodeDecodeError, TypeError) as err:  # code points past U+10FFFF
            raise ProtocolError("bad UTF-8 number") from err

    def tag(self, large_count: bool) -> ECTag:
        wire_name = self.number(2)
        tag_type = self.number(1)
        length = self.number(4)
        children = self.children(large_count) if wire_name & 1 else []
        # `length` counts children with fixed-size headers, whatever the number encoding.
        data_len = length - sum(_encoded_len(c) for c in children)
        if data_len < 0:
            raise ProtocolError("tag shorter than its children")
        try:
            kind = TagType(tag_type)
        except ValueError:
            kind = TagType.CUSTOM
        return ECTag(wire_name >> 1, kind, self.raw(data_len), children)

    def children(self, large_count: bool) -> list[ECTag]:
        count = self.number(2)
        if large_count and count == 0xFFFF:
            count = self.number(4)
        return [self.tag(large_count) for _ in range(count)]


def _encoded_len(tag: ECTag) -> int:
    """Size of a tag on the wire without UTF-8 numbers, as aMule computes tag lengths."""
    return 7 + (2 if tag.children else 0) + sum(_encoded_len(c) for c in tag.children) + len(tag.data)


def decode_body(flags: int, body: bytes) -> ECPacket:
    if flags & FLAG_ZLIB:
        try:
            body = zlib.decompress(body)
        except zlib.error as err:
            raise ProtocolError(f"bad zlib data: {err}") from err
    reader = _Reader(body, bool(flags & FLAG_UTF8_NUMBERS))
    op = reader.number(1)
    tags = reader.children(bool(flags & FLAG_LARGE_TAG_COUNT))
    return ECPacket(op, tags)


def decode(frame: bytes) -> ECPacket:
    """Decode one whole frame (header included). Used by tests and the fake daemon."""
    flags, length = HEADER.unpack_from(frame)
    if len(frame) != HEADER.size + length:
        raise ProtocolError("frame length mismatch")
    return decode_body(flags, frame[HEADER.size :])
