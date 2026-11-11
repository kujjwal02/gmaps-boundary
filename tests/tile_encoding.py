"""Encode synthetic spotlit tiles for tests, mirroring the wire layout Google sends."""

from __future__ import annotations

XOR_KEY = 0x9B
MASK_EXTENSION_FIELD = 40154408

Ring = list[tuple[int, int]]


def varint(number: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        encoded.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(encoded)


def zigzag(number: int) -> int:
    return (number << 1) ^ (number >> 63)


def bytes_field(number: int, payload: bytes) -> bytes:
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def area_feature(rings: list[Ring], *, is_mask: bool) -> bytes:
    packed_vertices = bytearray()
    ring_starts = bytearray()
    x = y = vertex_count = 0
    for ring_index, ring in enumerate(rings):
        if ring_index:
            ring_starts += varint(vertex_count)
        for vertex_x, vertex_y in ring:
            packed_vertices += varint(zigzag(vertex_x - x)) + varint(zigzag(vertex_y - y))
            x, y = vertex_x, vertex_y
            vertex_count += 1
    geometry = bytes_field(1, bytes(packed_vertices))
    if ring_starts:
        geometry += bytes_field(4, bytes(ring_starts))
    feature = bytes_field(1, geometry)
    if is_mask:
        feature += bytes_field(MASK_EXTENSION_FIELD, b"\x0a\x00")
    return feature


def tile_body(features: list[bytes] | None) -> bytes:
    """Return a tile body. ``None`` means the tile has no area layer at all."""
    message = bytes_field(1, varint(1 << 3) + varint(15))
    if features is not None:
        message += bytes_field(8, b"".join(bytes_field(1, feature) for feature in features))
    return bytes(byte ^ XOR_KEY for byte in message)
