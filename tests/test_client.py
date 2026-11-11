from __future__ import annotations

import asyncio

import httpx
import pytest
from shapely import Point, Polygon

import gmaps_boundary.client as client_module
from gmaps_boundary import (
    AsyncBoundaryClient,
    Boundary,
    BoundaryClient,
    NoBoundaryError,
    Place,
    PlaceNotFoundError,
    RequestFailedError,
    TooManyTilesError,
)

from .conftest import ReplayFactory

INDIRANAGAR = Place(
    feature_id="0x3bae16a418770391:0xb50f46b826501036",
    latitude=12.9783692,
    longitude=77.6408356,
    name="Indiranagar",
    address="Indiranagar, Bengaluru, Karnataka, India",
)
# The viewport Google Maps itself requests for Indiranagar: west, south, east, north.
INDIRANAGAR_VIEWPORT = (77.6285361, 12.9604117, 77.6478871, 12.9857080)
INDIRANAGAR_LABEL_POINT = Point(77.6408356, 12.9783692)


def sync_client(transport: httpx.MockTransport) -> BoundaryClient:
    return BoundaryClient(transport=transport, request_delay_s=0.0)


@pytest.fixture
def locality(replay: ReplayFactory) -> Boundary:
    with sync_client(replay("locality")) as client:
        return client.fetch_boundary("Indiranagar, Bengaluru")


def test_locality_resolves_the_place_by_name(locality: Boundary) -> None:
    assert locality.place == INDIRANAGAR
    assert locality.zoom == 17


def test_locality_bounds_match_the_google_viewport(locality: Boundary) -> None:
    assert locality.bounds == pytest.approx(INDIRANAGAR_VIEWPORT, abs=2e-6)


def test_locality_is_one_valid_polygon_without_holes(locality: Boundary) -> None:
    assert isinstance(locality.geometry, Polygon)
    assert locality.geometry.is_valid
    assert len(locality.geometry.interiors) == 0
    assert len(locality.geometry.exterior.coords) == 214


def test_locality_resolution_is_centimetres_at_zoom_17(locality: Boundary) -> None:
    assert locality.resolution_m == pytest.approx(0.0727, abs=0.0005)


def test_geojson_feature_carries_geometry_and_place(locality: Boundary) -> None:
    feature = locality.to_geojson()
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"] == {
        "name": "Indiranagar",
        "address": "Indiranagar, Bengaluru, Karnataka, India",
        "feature_id": "0x3bae16a418770391:0xb50f46b826501036",
        "label_latitude": 12.9783692,
        "label_longitude": 77.6408356,
        "zoom": 17,
    }
    assert locality.__geo_interface__ == feature


def test_a_place_object_skips_the_search_request(replay: ReplayFactory) -> None:
    requested: list[str] = []
    recorded = replay("locality")

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return recorded.handler(request)  # type: ignore[return-value]

    with sync_client(httpx.MockTransport(respond)) as client:
        boundary = client.fetch_boundary(INDIRANAGAR)
    assert boundary.zoom == 17
    assert "/search" not in requested


def test_explicit_coarse_zoom_gives_the_same_outline_with_fewer_vertices(
    replay: ReplayFactory, locality: Boundary
) -> None:
    with sync_client(replay("locality")) as client:
        coarse = client.fetch_boundary(INDIRANAGAR, zoom=12)
    assert coarse.zoom == 12
    assert len(coarse.geometry.exterior.coords) < 214  # type: ignore[union-attr]
    overlap = coarse.geometry.intersection(locality.geometry).area
    assert overlap / locality.geometry.area == pytest.approx(1.0, abs=0.01)


def test_async_client_returns_the_same_boundary(replay: ReplayFactory, locality: Boundary) -> None:
    async def fetch() -> Boundary:
        async with AsyncBoundaryClient(transport=replay("locality"), concurrency=8) as client:
            return await client.fetch_boundary("Indiranagar, Bengaluru")

    boundary = asyncio.run(fetch())
    assert boundary.place == locality.place
    assert boundary.geometry.equals(locality.geometry)


def test_postal_code_with_fill_only_tiles(replay: ReplayFactory) -> None:
    with sync_client(replay("postal_code")) as client:
        boundary = client.fetch_boundary("560038", zoom=16)
    assert boundary.place.name == "Bengaluru, Karnataka 560038"
    assert boundary.geometry.is_valid
    assert boundary.geometry.contains(INDIRANAGAR_LABEL_POINT)
    assert boundary.bounds == pytest.approx((77.629046, 12.973258, 77.665089, 13.004098), abs=2e-5)


def test_find_place_returns_the_place(replay: ReplayFactory) -> None:
    with sync_client(replay("locality")) as client:
        assert client.find_place("Indiranagar, Bengaluru") == INDIRANAGAR


def test_a_point_of_interest_raises_no_boundary(replay: ReplayFactory) -> None:
    with (
        sync_client(replay("no_boundary")) as client,
        pytest.raises(NoBoundaryError, match="Rameshwaram"),
    ):
        client.fetch_boundary("The Rameshwaram Cafe Indiranagar")


def test_an_unknown_name_raises_not_found(replay: ReplayFactory) -> None:
    with (
        sync_client(replay("not_found")) as client,
        pytest.raises(PlaceNotFoundError, match="zzqqxxnonexistentplace123"),
    ):
        client.fetch_boundary("zzqqxxnonexistentplace123")


def test_a_zoom_past_the_tile_cap_raises_before_fetching_fine_tiles(replay: ReplayFactory) -> None:
    with (
        sync_client(replay("locality")) as client,
        pytest.raises(TooManyTilesError, match="zoom 17 needs about"),
    ):
        client.fetch_boundary(INDIRANAGAR, zoom=17, max_tiles=16)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"zoom": 18}, "^zoom: expected 0 to 17"),
        ({"zoom": -1}, "^zoom: expected 0 to 17"),
        ({"max_tiles": 3}, "^max_tiles: expected at least 16"),
    ],
)
def test_bad_options_are_rejected_by_name(
    replay: ReplayFactory, arguments: dict[str, int], message: str
) -> None:
    with sync_client(replay("locality")) as client, pytest.raises(ValueError, match=message):
        client.fetch_boundary(INDIRANAGAR, **arguments)


def test_an_empty_query_is_rejected(replay: ReplayFactory) -> None:
    with sync_client(replay("locality")) as client, pytest.raises(ValueError, match=r"^query:"):
        client.fetch_boundary("  ")


def test_retryable_statuses_are_retried(
    replay: ReplayFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "_FIRST_RETRY_DELAY_S", 0.0)
    recorded = replay("locality")
    failures_left = 2

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal failures_left
        if failures_left:
            failures_left -= 1
            return httpx.Response(503)
        return recorded.handler(request)  # type: ignore[return-value]

    with sync_client(httpx.MockTransport(respond)) as client:
        assert client.find_place("Indiranagar, Bengaluru") == INDIRANAGAR
    assert failures_left == 0


def test_requests_fail_after_the_last_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_FIRST_RETRY_DELAY_S", 0.0)
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429)

    transport = httpx.MockTransport(respond)
    with (
        BoundaryClient(transport=transport, request_delay_s=0.0, max_retries=2) as client,
        pytest.raises(RequestFailedError, match="failed after 3 attempts"),
    ):
        client.find_place("Indiranagar")
    assert attempts == 3


def test_a_non_retryable_status_fails_at_once() -> None:
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(403)

    with (
        sync_client(httpx.MockTransport(respond)) as client,
        pytest.raises(RequestFailedError, match="HTTP 403"),
    ):
        client.find_place("Indiranagar")
    assert attempts == 1


def test_async_requests_fail_after_the_last_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_FIRST_RETRY_DELAY_S", 0.0)

    async def fetch() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        async with AsyncBoundaryClient(transport=transport, max_retries=1) as client:
            await client.find_place("Indiranagar")

    with pytest.raises(RequestFailedError, match="failed after 2 attempts"):
        asyncio.run(fetch())
