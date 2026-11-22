from __future__ import annotations

import struct
import zlib

import pytest

from ha_amule.ec.client import password_hash
from ha_amule.ec.codes import Op, Tag, TagType
from ha_amule.ec.packet import (
    FLAG_BASE,
    FLAG_UTF8_NUMBERS,
    FLAG_ZLIB,
    HEADER,
    ECPacket,
    ECTag,
    ProtocolError,
    decode,
    decode_body,
)


def test_integers_use_the_smallest_type() -> None:
    assert ECTag.uint(1, 200).type is TagType.UINT8
    assert ECTag.uint(1, 300).type is TagType.UINT16
    assert ECTag.uint(1, 70_000).type is TagType.UINT32
    assert ECTag.uint(1, 6_518_974_464).type is TagType.UINT64
    assert ECTag.uint(1, 6_518_974_464).value == 6_518_974_464
    with pytest.raises(ValueError, match="64 bits"):
        ECTag.uint(1, 1 << 64)


def test_value_types() -> None:
    assert ECTag.string(1, "ñandú.iso").value == "ñandú.iso"
    assert ECTag.hash16(1, "00" * 15 + "ff").value == "00" * 15 + "ff"
    assert ECTag.ipv4(1, "176.123.5.89", 4725).value == "176.123.5.89:4725"
    assert ECTag(1, TagType.DOUBLE, b"12.5\0").value == 12.5
    assert ECTag(1, TagType.UNKNOWN).value is None
    assert ECTag(1, TagType.CUSTOM, b"\x01\x02").value == b"\x01\x02"
    with pytest.raises(ValueError, match="16 bytes"):
        ECTag.hash16(1, b"short")


def test_wire_format_matches_amule() -> None:
    # A tag with one child: name<<1|1, type, length (child header 7 + child data 1), child count.
    tag = ECTag.uint(Tag.PARTFILE, 5, ECTag.uint(Tag.PARTFILE_PRIO, 2))
    assert tag.encode() == (
        struct.pack(">HBIH", (Tag.PARTFILE << 1) | 1, TagType.UINT8, 8 + 1, 1)
        + struct.pack(">HBI", Tag.PARTFILE_PRIO << 1, TagType.UINT8, 1)
        + b"\x02"
        + b"\x05"
    )
    frame = ECPacket(Op.PARTFILE_PRIO_SET, [tag]).encode()
    flags, length = HEADER.unpack_from(frame)
    assert flags == FLAG_BASE
    assert length == len(frame) - HEADER.size


def test_roundtrip_nested() -> None:
    packet = ECPacket(
        Op.STATS,
        [
            ECTag.uint(Tag.STATS_DL_SPEED, 12345),
            ECTag.uint(
                Tag.CONNSTATE,
                0x1D,
                ECTag.ipv4(Tag.SERVER, "1.2.3.4", 4661),
                ECTag.uint(Tag.ED2K_ID, 2_130_706_433),
            ),
        ],
    )
    packet.tags[1].children[0].children.append(ECTag.string(Tag.SERVER_NAME, "Sunrise"))
    decoded = decode(packet.encode())
    assert decoded == packet
    state = decoded.first(Tag.CONNSTATE)
    assert state is not None
    server = state.child(Tag.SERVER)
    assert server is not None
    assert server.str_of(Tag.SERVER_NAME) == "Sunrise"
    assert state.int_of(Tag.ED2K_ID) == 2_130_706_433
    assert state.int_of(Tag.KAD_ID, 7) == 7
    assert decoded.all(Tag.STATS_DL_SPEED)[0].value == 12345
    assert decoded.describe() == "STATS"
    assert ECPacket(0xEE).describe() == "0xee"


def _utf8(n: int) -> bytes:
    return chr(n).encode("utf-8", "surrogatepass")


def test_decodes_utf8_numbers_and_zlib() -> None:
    # The same packet as amuled sends it when both sides negotiated UTF-8 numbers.
    data = b"\x00\x00\x30\x39"  # 12345 as UINT16 data is not UTF-8 encoded
    body = _utf8(Op.STATS) + _utf8(1) + _utf8(Tag.STATS_DL_SPEED << 1) + _utf8(TagType.UINT32) + _utf8(len(data)) + data
    packet = decode_body(FLAG_BASE | FLAG_UTF8_NUMBERS, body)
    assert packet.op == Op.STATS
    assert packet.tags[0].name == Tag.STATS_DL_SPEED
    assert packet.tags[0].value == 12345

    plain = ECPacket(Op.NOOP, [ECTag.string(Tag.STRING, "x" * 2000)]).encode()[HEADER.size :]
    assert decode_body(FLAG_BASE | FLAG_ZLIB, zlib.compress(plain)).strings() == ["x" * 2000]
    with pytest.raises(ProtocolError, match="zlib"):
        decode_body(FLAG_BASE | FLAG_ZLIB, b"not zlib")


def test_rejects_malformed_frames() -> None:
    frame = ECPacket(Op.NOOP, [ECTag.string(Tag.STRING, "hello")]).encode()
    with pytest.raises(ProtocolError, match="length"):
        decode(frame[:-1])
    with pytest.raises(ProtocolError, match="truncated"):
        decode_body(FLAG_BASE, frame[HEADER.size : -2])
    # A tag claiming less data than its children occupy.
    bad = struct.pack(">BHHBIH", Op.NOOP, 1, (1 << 1) | 1, TagType.UINT8, 0, 1) + ECTag.uint(2, 1).encode()
    with pytest.raises(ProtocolError, match="shorter"):
        decode_body(FLAG_BASE, bad)


def test_password_hash() -> None:
    # md5(md5hex("secret") + md5hex("%X" % salt)), as aMule's ExternalConn computes it.
    # Verified against a real amuled 2.3.3 during development.
    assert password_hash("secret", 0x1234ABCD).hex() == "89e17d3c82aeb8eb245fa2d42750e25c"
