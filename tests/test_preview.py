from __future__ import annotations

import io
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest
from shapely import box

from gmaps_boundary import Boundary, Place, RequestFailedError
from gmaps_boundary.preview import Basemap, _frame, save_preview

BOUNDARY = Boundary(
    place=Place(feature_id="0x1:0x2", latitude=12.973, longitude=77.638, name="Test area"),
    zoom=17,
    geometry=box(77.6285, 12.9604, 77.6479, 12.9857),
)


def tile_png() -> bytes:
    buffer = io.BytesIO()
    plt.imsave(buffer, [[(0.9, 0.9, 0.9)] * 4] * 4, format="png")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("basemap", "host"), [("google", "mt1.google.com"), ("osm", "tile.openstreetmap.org")]
)
def test_map_preview_fetches_a_bounded_number_of_tiles(
    tmp_path: Path, basemap: Basemap, host: str
) -> None:
    requested: list[httpx.URL] = []
    png = tile_png()

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        return httpx.Response(200, content=png)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        save_preview(BOUNDARY, tmp_path / "map.png", basemap=basemap, http_client=http_client)
    assert (tmp_path / "map.png").read_bytes().startswith(b"\x89PNG")
    assert 1 <= len(requested) <= 20
    assert {url.host for url in requested} == {host}
    assert len(set(requested)) == len(requested)


def test_osm_tiles_are_requested_with_a_client_name_that_identifies_the_library(
    tmp_path: Path,
) -> None:
    client_names: set[str] = set()
    png = tile_png()

    def respond(request: httpx.Request) -> httpx.Response:
        client_names.add(request.headers["user-agent"].split("/")[0])
        return httpx.Response(200, content=png)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        save_preview(BOUNDARY, tmp_path / "map.png", basemap="osm", http_client=http_client)
    assert client_names == {"gmaps-boundary"}


def test_a_wide_aspect_widens_the_frame_and_keeps_the_boundary_inside() -> None:
    fitted = _frame(BOUNDARY, 15, None)
    wide = _frame(BOUNDARY, 15, 2.0)
    assert (wide[2] - wide[0]) / (wide[3] - wide[1]) == pytest.approx(2.0)
    assert wide[0] < fitted[0]
    assert wide[2] > fitted[2]
    assert (wide[1], wide[3]) == pytest.approx((fitted[1], fitted[3]))


def test_map_preview_raises_when_a_tile_is_refused(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    with (
        httpx.Client(transport=transport) as http_client,
        pytest.raises(RequestFailedError, match="HTTP 403; pass basemap='none'"),
    ):
        save_preview(BOUNDARY, tmp_path / "map.png", http_client=http_client)
    assert not (tmp_path / "map.png").exists()


def test_outline_only_preview_makes_no_request(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        save_preview(BOUNDARY, tmp_path / "plain.png", basemap="none", http_client=http_client)
    assert (tmp_path / "plain.png").read_bytes().startswith(b"\x89PNG")


def test_an_unknown_basemap_is_rejected_with_the_valid_options(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match=r"^basemap: expected one of google, osm, none, got 'bing'"
    ):
        save_preview(BOUNDARY, tmp_path / "map.png", basemap="bing")  # type: ignore[arg-type]
