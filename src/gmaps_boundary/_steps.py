"""The request plan for one boundary, written without I/O.

Each function here is a generator. It yields a batch of URLs, receives the
response bodies in the same order, and returns its value when done. The sync and
async clients run the same generators, so the logic exists once.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from typing import TypeVar

import shapely
from shapely import MultiPolygon, Polygon, set_precision, unary_union
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from ._boundary import Boundary, PolygonalGeometry
from ._places import Place, parse_search_response, search_url
from ._tiles import (
    MAX_ZOOM,
    TILE_EXTENT,
    Tile,
    decode_place_part,
    global_units_to_lng_lat,
    tile_containing,
    tile_url,
)
from .errors import NoBoundaryError, TooManyTilesError

ReturnValue = TypeVar("ReturnValue")
Steps = Generator[list[str], list[bytes], ReturnValue]
PlaceQuery = str | Place

# The outline is first read at a coarse zoom, to size the job and to seed the fine pass.
_COARSE_ZOOMS = (12, 8, 4, 0)
_PROBE_ZOOM = 10
# The tile estimate is rough, so automatic zoom aims below the cap.
_AUTO_ZOOM_FILL_RATIO = 0.75


@dataclass(frozen=True)
class FetchOptions:
    zoom: int | None
    max_tiles: int
    language: str
    region: str
    batch_size: int

    def __post_init__(self) -> None:
        if self.zoom is not None and not 0 <= self.zoom <= MAX_ZOOM:
            raise ValueError(f"zoom: expected 0 to {MAX_ZOOM} or None, got {self.zoom}")
        if self.max_tiles < 16:
            raise ValueError(f"max_tiles: expected at least 16, got {self.max_tiles}")
        if self.batch_size < 1:
            raise ValueError(f"batch_size: expected at least 1, got {self.batch_size}")


class _WalkTooLargeError(Exception):
    """A tile walk passed the tile cap."""


def place_steps(query: PlaceQuery, language: str, region: str) -> Steps[Place]:
    """Resolve a place from a ``Place``, a Google Maps place URL or a search text."""
    if isinstance(query, Place):
        return query
    if query.startswith(("http://", "https://")):
        return Place.from_url(query)
    if not query.strip():
        raise ValueError(
            "query: expected a place name or a Google Maps place URL, got an empty text"
        )
    (body,) = yield [search_url(query, language, region)]
    return parse_search_response(body, query)


def _polygons_only(geometry: BaseGeometry) -> PolygonalGeometry:
    """Drop the stray points and lines a union can leave, and keep the polygons."""
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    polygons = [part for part in getattr(geometry, "geoms", []) if isinstance(part, Polygon)]
    return MultiPolygon(polygons)


def _walk_steps(
    place: Place, seeds: Iterable[Tile], tile_cap: int, options: FetchOptions
) -> Steps[PolygonalGeometry]:
    """Fetch tiles outward from ``seeds`` and merge the place parts, in zoom-level units."""
    pending = deque(dict.fromkeys(seeds))
    seen = set(pending)
    parts: list[BaseGeometry] = []
    while pending:
        if len(seen) > tile_cap:
            raise _WalkTooLargeError
        batch = [pending.popleft() for _ in range(min(len(pending), options.batch_size))]
        bodies = yield [
            tile_url(tile, place.cell_id, place.feature_number, options.language, options.region)
            for tile in batch
        ]
        for tile, body in zip(batch, bodies, strict=True):
            part = decode_place_part(body, tile).geometry
            if part.is_empty:
                continue
            parts.append(set_precision(part, 1.0))
            for neighbour in tile.neighbours():
                if neighbour not in seen:
                    seen.add(neighbour)
                    pending.append(neighbour)
    # Zero tolerance drops only the collinear vertices the tile seams leave behind.
    return _polygons_only(unary_union(parts).simplify(0))


def _label_seeds(place: Place, zoom: int) -> list[Tile]:
    """The tile under the label point and its ring. The label can sit just off the polygon."""
    centre = tile_containing(place.latitude, place.longitude, zoom)
    tiles_per_side = 1 << zoom
    return [
        Tile(zoom, centre.x + dx, centre.y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if 0 <= centre.x + dx < tiles_per_side and 0 <= centre.y + dy < tiles_per_side
    ]


def _outline_seeds(coarse: PolygonalGeometry, coarse_zoom: int, zoom: int) -> list[Tile]:
    """Every tile at ``zoom`` that touches the coarse outline, with half a tile of margin."""
    scale = 1 << (zoom - coarse_zoom)
    reach = shapely.transform(coarse, lambda points: points * scale).buffer(TILE_EXTENT / 2)
    prepared_reach = prep(reach)
    west, north, east, south = (int(edge // TILE_EXTENT) for edge in reach.bounds)
    last = (1 << zoom) - 1
    return [
        tile
        for x in range(max(west, 0), min(east, last) + 1)
        for y in range(max(north, 0), min(south, last) + 1)
        if prepared_reach.intersects((tile := Tile(zoom, x, y)).square)
    ]


def _estimated_tiles(coarse: PolygonalGeometry, coarse_zoom: int, zoom: int) -> float:
    """Roughly how many tiles a walk at ``zoom`` fetches: the inside plus a ring both sides."""
    scale = 1 << (zoom - coarse_zoom)
    inside_tiles = coarse.area / (TILE_EXTENT * TILE_EXTENT) * scale * scale
    outline_tiles = coarse.length / TILE_EXTENT * scale
    return inside_tiles + 2 * outline_tiles + 4


def _require_boundary_steps(place: Place, options: FetchOptions) -> Steps[None]:
    """Raise when Google draws no boundary for the place.

    A tile on the far side of the world is outside any real place. For a place with a
    boundary it carries a full mask. For a place without one it carries no mask.
    """
    near = tile_containing(place.latitude, place.longitude, _PROBE_ZOOM)
    tiles_per_side = 1 << _PROBE_ZOOM
    far = Tile(_PROBE_ZOOM, (near.x + tiles_per_side // 2) % tiles_per_side, near.y)
    (body,) = yield [
        tile_url(far, place.cell_id, place.feature_number, options.language, options.region)
    ]
    if not decode_place_part(body, far).has_mask:
        label = place.name or place.feature_id
        raise NoBoundaryError(
            f"Google Maps draws no boundary for {label!r}. "
            "Boundaries exist for areas such as localities, cities and postal codes."
        )


def _coarse_outline_steps(
    place: Place, finest_zoom: int, options: FetchOptions
) -> Steps[tuple[PolygonalGeometry, int]]:
    """Read the outline at the first coarse zoom that fits the tile cap."""
    for coarse_zoom in _COARSE_ZOOMS:
        if coarse_zoom > finest_zoom:
            continue
        try:
            coarse = yield from _walk_steps(
                place, _label_seeds(place, coarse_zoom), options.max_tiles, options
            )
        except _WalkTooLargeError:
            continue
        return coarse, coarse_zoom
    raise TooManyTilesError(
        f"the place needs more than max_tiles={options.max_tiles} tiles even at zoom 0"
    )


def _finest_zoom_within_cap(
    coarse: PolygonalGeometry, coarse_zoom: int, options: FetchOptions
) -> int:
    tile_budget = options.max_tiles * _AUTO_ZOOM_FILL_RATIO
    for zoom in range(MAX_ZOOM, coarse_zoom, -1):
        if _estimated_tiles(coarse, coarse_zoom, zoom) <= tile_budget:
            return zoom
    return coarse_zoom


def boundary_steps(query: PlaceQuery, options: FetchOptions) -> Steps[Boundary]:
    """The whole job: resolve the place, check it has a boundary, read the outline."""
    place = yield from place_steps(query, options.language, options.region)
    yield from _require_boundary_steps(place, options)
    finest_zoom = MAX_ZOOM if options.zoom is None else options.zoom
    coarse, coarse_zoom = yield from _coarse_outline_steps(place, finest_zoom, options)

    if coarse.is_empty:
        # The place is too small to show at the coarse zoom. Read it at the finest zoom directly.
        try:
            outline = yield from _walk_steps(
                place, _label_seeds(place, finest_zoom), options.max_tiles, options
            )
        except _WalkTooLargeError as error:
            raise TooManyTilesError(
                f"the place needs more than max_tiles={options.max_tiles} tiles "
                f"at zoom {finest_zoom}"
            ) from error
        zoom = finest_zoom
    elif options.zoom is None:
        zoom = _finest_zoom_within_cap(coarse, coarse_zoom, options)
        outline = coarse
        while zoom > coarse_zoom:
            try:
                outline = yield from _walk_steps(
                    place, _outline_seeds(coarse, coarse_zoom, zoom), options.max_tiles, options
                )
                break
            except _WalkTooLargeError:
                zoom -= 1
    else:
        zoom = options.zoom
        outline = coarse
        if zoom > coarse_zoom:
            estimate = _estimated_tiles(coarse, coarse_zoom, zoom)
            too_many = TooManyTilesError(
                f"zoom {zoom} needs about {estimate:.0f} tiles, more than max_tiles="
                f"{options.max_tiles}. Lower zoom, raise max_tiles, or pass zoom=None."
            )
            if estimate > options.max_tiles:
                raise too_many
            try:
                outline = yield from _walk_steps(
                    place, _outline_seeds(coarse, coarse_zoom, zoom), options.max_tiles, options
                )
            except _WalkTooLargeError as error:
                raise too_many from error

    if outline.is_empty:
        raise NoBoundaryError(
            f"no boundary found near the label point of {place.name or place.feature_id!r}"
        )
    geometry = shapely.transform(outline, lambda points: global_units_to_lng_lat(points, zoom))
    return Boundary(place=place, zoom=zoom, geometry=_polygons_only(geometry))
