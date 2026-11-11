from __future__ import annotations

import numpy
import pytest
from shapely import box

from gmaps_boundary import ResponseFormatError
from gmaps_boundary._tiles import (
    TILE_EXTENT,
    Tile,
    decode_place_part,
    global_units_to_lng_lat,
    tile_containing,
    tile_url,
)

from .tile_encoding import Ring, area_feature, tile_body

TILE = Tile(15, 23450, 15191)
ORIGIN_X, ORIGIN_Y = TILE.x * TILE_EXTENT, TILE.y * TILE_EXTENT
OVERSCAN_SQUARE: Ring = [(-24, -24), (4120, -24), (4120, 4120), (-24, 4120)]
# The place covers the left half of the tile and runs past the tile edge, as real masks do.
PLACE_RING: Ring = [(-24, -24), (2048, -24), (2048, 4120), (-24, 4120)]
LEFT_HALF = box(ORIGIN_X, ORIGIN_Y, ORIGIN_X + 2048, ORIGIN_Y + TILE_EXTENT)


def test_tile_containing_matches_the_known_indiranagar_tile() -> None:
    assert tile_containing(12.9783692, 77.6408356, 15) == Tile(15, 23451, 15192)


def test_tile_containing_clamps_the_poles_into_the_tile_range() -> None:
    assert tile_containing(89.9, 179.9999, 3) == Tile(3, 7, 0)
    assert tile_containing(-89.9, -180.0, 3) == Tile(3, 0, 7)


def test_neighbours_stay_inside_the_world() -> None:
    assert set(Tile(1, 0, 0).neighbours()) == {Tile(1, 1, 0), Tile(1, 0, 1)}
    assert len(Tile(15, 100, 100).neighbours()) == 4


def test_global_units_round_trip_to_the_tile_corner() -> None:
    corner = numpy.array([[23451 * TILE_EXTENT, 15192 * TILE_EXTENT]], dtype=numpy.float64)
    longitude, latitude = global_units_to_lng_lat(corner, 15)[0]
    assert tile_containing(latitude - 1e-9, longitude + 1e-9, 15) == Tile(15, 23451, 15192)
    assert longitude == pytest.approx(23451 / 32768 * 360 - 180, abs=1e-12)


def test_tile_url_carries_tile_place_and_locale() -> None:
    url = tile_url(TILE, cell_id=11, feature_id=22, language="hi", region="in")
    assert "!1i15!2i23450!3i15191" in url
    assert "!2shi!3sin" in url
    assert "!1y11!2y22!8b1" in url


def test_mask_tile_yields_the_square_minus_the_mask() -> None:
    body = tile_body([area_feature([OVERSCAN_SQUARE, PLACE_RING], is_mask=True)])
    part = decode_place_part(body, TILE)
    assert part.has_mask
    assert part.geometry.equals(LEFT_HALF)


def test_full_mask_tile_is_outside_the_place() -> None:
    part = decode_place_part(tile_body([area_feature([OVERSCAN_SQUARE], is_mask=True)]), TILE)
    assert part.has_mask
    assert part.geometry.is_empty


def test_tile_without_an_area_layer_counts_as_inside() -> None:
    part = decode_place_part(tile_body(None), TILE)
    assert not part.has_mask
    assert part.geometry.equals(TILE.square)


def test_fill_only_tile_yields_the_fill() -> None:
    fill_ring: Ring = [(0, 0), (2048, 0), (2048, 4096), (0, 4096)]
    part = decode_place_part(tile_body([area_feature([fill_ring], is_mask=False)]), TILE)
    assert not part.has_mask
    assert part.geometry.equals(LEFT_HALF)


def test_agreeing_mask_and_fill_pass_the_cross_check() -> None:
    fill_ring: Ring = [(0, 0), (2048, 0), (2048, 4096), (0, 4096)]
    body = tile_body(
        [
            area_feature([fill_ring], is_mask=False),
            area_feature([OVERSCAN_SQUARE, PLACE_RING], is_mask=True),
        ]
    )
    assert decode_place_part(body, TILE).geometry.equals(LEFT_HALF)


def test_disagreeing_mask_and_fill_raise() -> None:
    wrong_fill: Ring = [(0, 0), (1024, 0), (1024, 4096), (0, 4096)]
    body = tile_body(
        [
            area_feature([wrong_fill], is_mask=False),
            area_feature([OVERSCAN_SQUARE, PLACE_RING], is_mask=True),
        ]
    )
    with pytest.raises(ResponseFormatError, match="mask and fill disagree"):
        decode_place_part(body, TILE)


def test_empty_area_layer_raises() -> None:
    with pytest.raises(ResponseFormatError, match="neither mask nor fill"):
        decode_place_part(tile_body([]), TILE)
