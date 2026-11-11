from __future__ import annotations

import pytest

from gmaps_boundary import ResponseFormatError
from gmaps_boundary._protobuf import (
    first_bytes_field,
    read_fields,
    read_packed_varints,
    read_varint,
    unzigzag,
)


def test_read_varint_reads_multi_byte_values() -> None:
    assert read_varint(bytes([0x91, 0xB7, 0x01, 0xFF]), 0) == (23441, 3)


def test_read_varint_rejects_a_truncated_value() -> None:
    with pytest.raises(ResponseFormatError, match="runs past the end"):
        read_varint(bytes([0x91, 0xB7]), 0)


def test_read_fields_decodes_every_wire_type() -> None:
    message = (
        bytes([0x08, 0x0F])  # field 1, varint 15
        + bytes([0x12, 0x02, 0xAA, 0xBB])  # field 2, two bytes
        + bytes([0x2D, 1, 2, 3, 4])  # field 5, fixed32
        + bytes([0x19, 1, 2, 3, 4, 5, 6, 7, 8])  # field 3, fixed64
    )
    assert read_fields(message) == [
        (1, 15),
        (2, b"\xaa\xbb"),
        (5, bytes([1, 2, 3, 4])),
        (3, bytes([1, 2, 3, 4, 5, 6, 7, 8])),
    ]


def test_read_fields_rejects_an_overlong_field() -> None:
    with pytest.raises(ResponseFormatError, match="field 2 runs past the end"):
        read_fields(bytes([0x12, 0x05, 0xAA]))


def test_read_fields_rejects_an_unknown_wire_type() -> None:
    with pytest.raises(ResponseFormatError, match="unknown wire type 3"):
        read_fields(bytes([0x0B]))


def test_first_bytes_field_returns_none_when_absent() -> None:
    assert first_bytes_field([(1, 15)], 2) is None


def test_first_bytes_field_rejects_a_varint_field() -> None:
    with pytest.raises(ResponseFormatError, match="not length-delimited"):
        first_bytes_field([(1, 15)], 1)


def test_packed_varints_and_zigzag() -> None:
    assert [unzigzag(n) for n in read_packed_varints(bytes([0x2F, 0x2F, 0xE0, 0x40, 0x00]))] == [
        -24,
        -24,
        4144,
        0,
    ]
