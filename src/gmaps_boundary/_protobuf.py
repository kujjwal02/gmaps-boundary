"""Schema-free protobuf wire decoding, enough to read Google vector tiles."""

from __future__ import annotations

from .errors import ResponseFormatError

FieldValue = int | bytes

_VARINT = 0
_FIXED64 = 1
_LENGTH_DELIMITED = 2
_FIXED32 = 5
_MAX_VARINT_BYTES = 10


def read_varint(buffer: bytes, position: int) -> tuple[int, int]:
    """Return the varint at ``position`` and the position after it."""
    value = 0
    for byte_index in range(_MAX_VARINT_BYTES):
        if position >= len(buffer):
            raise ResponseFormatError("protobuf: varint runs past the end of its message")
        byte = buffer[position]
        position += 1
        value |= (byte & 0x7F) << (7 * byte_index)
        if not byte & 0x80:
            return value, position
    raise ResponseFormatError("protobuf: varint is longer than 10 bytes")


def read_fields(message: bytes) -> list[tuple[int, FieldValue]]:
    """Decode one message into ``(field number, value)`` pairs, in wire order."""
    fields: list[tuple[int, FieldValue]] = []
    position = 0
    while position < len(message):
        key, position = read_varint(message, position)
        number, wire_type = key >> 3, key & 7
        if wire_type == _VARINT:
            value, position = read_varint(message, position)
            fields.append((number, value))
            continue
        if wire_type == _LENGTH_DELIMITED:
            size, position = read_varint(message, position)
        elif wire_type == _FIXED64:
            size = 8
        elif wire_type == _FIXED32:
            size = 4
        else:
            raise ResponseFormatError(f"protobuf: field {number} has unknown wire type {wire_type}")
        if position + size > len(message):
            raise ResponseFormatError(f"protobuf: field {number} runs past the end of its message")
        fields.append((number, message[position : position + size]))
        position += size
    return fields


def read_packed_varints(packed: bytes) -> list[int]:
    numbers: list[int] = []
    position = 0
    while position < len(packed):
        number, position = read_varint(packed, position)
        numbers.append(number)
    return numbers


def unzigzag(number: int) -> int:
    return (number >> 1) ^ -(number & 1)


def first_bytes_field(fields: list[tuple[int, FieldValue]], number: int) -> bytes | None:
    """Return the first length-delimited value of field ``number``, or None when absent."""
    for field_number, value in fields:
        if field_number == number:
            if not isinstance(value, bytes):
                raise ResponseFormatError(f"protobuf: field {number} is not length-delimited")
            return value
    return None
