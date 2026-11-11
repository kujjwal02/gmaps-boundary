"""Fetch one spotlit tile and print it as a field tree.

Usage: uv run python scripts/dump_tile.py "<place name or URL>" <zoom> <x> <y>
"""

from __future__ import annotations

import sys

import httpx

from gmaps_boundary import ResponseFormatError, find_place
from gmaps_boundary._protobuf import read_fields, read_packed_varints, unzigzag
from gmaps_boundary._tiles import Tile, tile_url
from gmaps_boundary.client import DEFAULT_USER_AGENT

XOR_KEY = 0x9B
AREA_LAYER_PATH = (8, 1, 1)
VERTICES_FIELD = 1
MAX_DEPTH = 5


def print_vertices(packed: bytes, indent: str) -> None:
    deltas = [unzigzag(number) for number in read_packed_varints(packed)]
    x = y = 0
    vertices = []
    for index in range(0, len(deltas) - 1, 2):
        x += deltas[index]
        y += deltas[index + 1]
        vertices.append((x, y))
    print(f"{indent}vertices ({len(vertices)}): {vertices}")


def print_tree(message: bytes, path: tuple[int, ...]) -> None:
    indent = "  " * len(path)
    for number, value in read_fields(message):
        here = (*path, number)
        if isinstance(value, int):
            print(f"{indent}{number}: {value}")
            continue
        if path == AREA_LAYER_PATH and number == VERTICES_FIELD:
            print_vertices(value, indent)
            continue
        try:
            is_message = len(value) > 1 and len(here) < MAX_DEPTH and bool(read_fields(value))
        except ResponseFormatError:
            is_message = False
        if is_message:
            print(f"{indent}{number}: message, {len(value)} bytes")
            print_tree(value, here)
        else:
            print(f"{indent}{number}: bytes, {len(value)}: {value[:24].hex(' ')}")


def main() -> None:
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    place = find_place(sys.argv[1])
    tile = Tile(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    url = tile_url(tile, place.cell_id, place.feature_number, "en", "us")
    response = httpx.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=20.0)
    print(f"place: {place.name} {place.feature_id}")
    print(f"HTTP {response.status_code}, {len(response.content)} bytes")
    print(f"first raw bytes: {response.content[:12].hex(' ')}")
    print_tree(bytes(byte ^ XOR_KEY for byte in response.content), ())


if __name__ == "__main__":
    main()
