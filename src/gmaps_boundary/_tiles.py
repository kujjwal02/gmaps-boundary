"""Tile addressing, tile URLs and decoding of the Google Maps "spotlit" layer.

Google Maps highlights a searched place through a vector tile layer named
``spotlit``. Each tile of that layer carries a mask polygon that dims everything
outside the place. The place itself is the tile square minus the mask. A tile
inside the place carries a fill polygon without a mask, or no area layer at all.
Coordinates are integers in 1/4096 of a tile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
from numpy.typing import NDArray
from shapely import Polygon, box, unary_union
from shapely.geometry.base import BaseGeometry

from ._protobuf import first_bytes_field, read_fields, read_packed_varints, unzigzag
from .errors import ResponseFormatError

TILE_EXTENT = 4096
# The spotlit layer is empty above this zoom.
MAX_ZOOM = 17

_XOR_KEY = 0x9B
_AREA_LAYER_FIELD = 8
_FEATURE_FIELD = 1
_GEOMETRY_FIELD = 1
_VERTICES_FIELD = 1
_RING_STARTS_FIELD = 4
# Only the mask feature carries this extension. The place fill does not.
_MASK_EXTENSION_FIELD = 40154408
# Mask and fill round their vertices separately, which leaves slivers of a few hundred
# square units. A wrong ring rule is off by a large share of the 16.7M-unit tile.
_MAX_FILL_MISMATCH_UNITS = TILE_EXTENT * TILE_EXTENT / 100

_TILE_URL = (
    "https://www.google.com/maps/vt/pb=!1m4!1m3!1i{zoom}!2i{x}!3i{y}"
    "!2m2!1e2!2sspotlit"
    "!3m8!2s{language}!3s{region}!5e1105!12m4!1e68!2m2!1sset!2sRoadmap!4e1"
    "!5m4!1e4!8m2!1e0!1e1!6m11!1e12!2i2!19m1!1e0!20m1!1e0!39b1!44e1!50e0!67m1!1e1"
    "!27m6!299174093m5!14m4!1m3!1m2!1y{cell_id}!2y{feature_id}!8b1"
)


@dataclass(frozen=True)
class Tile:
    zoom: int
    x: int
    y: int

    @property
    def square(self) -> Polygon:
        """The tile outline in zoom-level global units."""
        return box(
            self.x * TILE_EXTENT,
            self.y * TILE_EXTENT,
            (self.x + 1) * TILE_EXTENT,
            (self.y + 1) * TILE_EXTENT,
        )

    def neighbours(self) -> list[Tile]:
        """The edge-adjacent tiles that exist at this zoom."""
        tiles_per_side = 1 << self.zoom
        adjacent = [
            Tile(self.zoom, self.x + dx, self.y + dy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        ]
        return [
            tile
            for tile in adjacent
            if 0 <= tile.x < tiles_per_side and 0 <= tile.y < tiles_per_side
        ]


@dataclass(frozen=True)
class PlacePart:
    """The part of a place inside one tile, in zoom-level global units."""

    geometry: BaseGeometry
    # A tile outside or across the boundary has a mask. A tile with no area layer has none:
    # Google sends that both inside a place and for a place that has no boundary.
    has_mask: bool


def tile_url(tile: Tile, cell_id: int, feature_id: int, language: str, region: str) -> str:
    return _TILE_URL.format(
        zoom=tile.zoom,
        x=tile.x,
        y=tile.y,
        language=language,
        region=region,
        cell_id=cell_id,
        feature_id=feature_id,
    )


def tile_containing(latitude: float, longitude: float, zoom: int) -> Tile:
    tiles_per_side = 1 << zoom
    x = (longitude + 180.0) / 360.0 * tiles_per_side
    y = (1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * tiles_per_side
    last = tiles_per_side - 1
    return Tile(zoom, min(max(int(x), 0), last), min(max(int(y), 0), last))


def global_units_to_lng_lat(points: NDArray[numpy.float64], zoom: int) -> NDArray[numpy.float64]:
    """Convert an (n, 2) array of zoom-level global units to (longitude, latitude)."""
    world_units = (1 << zoom) * TILE_EXTENT
    longitude = points[:, 0] / world_units * 360.0 - 180.0
    latitude = numpy.degrees(
        numpy.arctan(numpy.sinh(numpy.pi * (1.0 - 2.0 * points[:, 1] / world_units)))
    )
    return numpy.column_stack([longitude, latitude])


def _decode_rings(geometry: bytes) -> list[list[tuple[int, int]]]:
    """Split an area geometry into rings of tile-local vertices."""
    fields = read_fields(geometry)
    packed_vertices = first_bytes_field(fields, _VERTICES_FIELD)
    if packed_vertices is None:
        raise ResponseFormatError("tile: area geometry has no vertex field")
    deltas = [unzigzag(number) for number in read_packed_varints(packed_vertices)]
    if len(deltas) % 2:
        raise ResponseFormatError("tile: area geometry has an odd number of coordinates")
    vertices: list[tuple[int, int]] = []
    x = y = 0
    for index in range(0, len(deltas), 2):
        x += deltas[index]
        y += deltas[index + 1]
        vertices.append((x, y))
    packed_ring_starts = first_bytes_field(fields, _RING_STARTS_FIELD)
    later_ring_starts = read_packed_varints(packed_ring_starts) if packed_ring_starts else []
    ring_starts = [0, *later_ring_starts]
    ring_ends = [*later_ring_starts, len(vertices)]
    if ring_starts != sorted(ring_starts) or ring_starts[-1] > len(vertices):
        raise ResponseFormatError("tile: area geometry ring starts are out of order")
    return [vertices[start:end] for start, end in zip(ring_starts, ring_ends, strict=True)]


def _compose_rings(geometry: bytes, tile: Tile) -> BaseGeometry:
    """Return one area in zoom-level global units from its rings."""
    area: BaseGeometry = Polygon()
    origin_x, origin_y = tile.x * TILE_EXTENT, tile.y * TILE_EXTENT
    for ring in _decode_rings(geometry):
        if len(ring) < 3:
            continue
        ring_polygon = Polygon([(origin_x + x, origin_y + y) for x, y in ring]).buffer(0)
        # Rings compose even-odd: a ring inside another ring is a hole.
        area = area.symmetric_difference(ring_polygon)
    return area


def decode_place_part(tile_body: bytes, tile: Tile) -> PlacePart:
    """Decode one spotlit tile body into the part of the place inside that tile."""
    fields = read_fields(bytes(byte ^ _XOR_KEY for byte in tile_body))
    area_layer = first_bytes_field(fields, _AREA_LAYER_FIELD)
    if area_layer is None:
        return PlacePart(geometry=tile.square, has_mask=False)
    masks: list[BaseGeometry] = []
    fills: list[BaseGeometry] = []
    for number, feature in read_fields(area_layer):
        if number != _FEATURE_FIELD or not isinstance(feature, bytes):
            continue
        feature_fields = read_fields(feature)
        geometry = first_bytes_field(feature_fields, _GEOMETRY_FIELD)
        if geometry is None:
            continue
        is_mask = any(field_number == _MASK_EXTENSION_FIELD for field_number, _ in feature_fields)
        (masks if is_mask else fills).append(_compose_rings(geometry, tile))
    if not masks:
        if not fills:
            raise ResponseFormatError(f"tile {tile}: area layer has neither mask nor fill")
        # Some place kinds send a tile inside the place as a fill with no mask.
        return PlacePart(geometry=unary_union(fills).intersection(tile.square), has_mask=False)
    place_part = tile.square.difference(unary_union(masks))
    # The tile also draws the place fill directly. The two must agree, or the ring rule is wrong.
    mismatch_units = place_part.symmetric_difference(unary_union(fills)).area
    if fills and mismatch_units > _MAX_FILL_MISMATCH_UNITS:
        raise ResponseFormatError(
            f"tile {tile}: mask and fill disagree by {mismatch_units:.0f} square units"
        )
    return PlacePart(geometry=place_part, has_mask=True)
