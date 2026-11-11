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
from gmaps_boundary.preview import save_preview

BOUNDARY = Boundary(
    place=Place(feature_id="0x1:0x2", latitude=12.973, longitude=77.638, name="Test area"),
    zoom=17,
    geometry=box(77.6285, 12.9604, 77.6479, 12.9857),
)


def tile_png() -> bytes:
    buffer = io.BytesIO()
    plt.imsave(buffer, [[(0.9, 0.9, 0.9)] * 4] * 4, format="png")
    return buffer.getvalue()


def test_basemap_preview_fetches_a_bounded_number_of_osm_tiles(tmp_path: Path) -> None:
    requested: list[httpx.URL] = []
    png = tile_png()

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        return httpx.Response(200, content=png)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        save_preview(BOUNDARY, tmp_path / "map.png", http_client=http_client)
    assert (tmp_path / "map.png").read_bytes().startswith(b"\x89PNG")
    assert 1 <= len(requested) <= 20
    assert {url.host for url in requested} == {"tile.openstreetmap.org"}
    assert len(set(requested)) == len(requested)


def test_basemap_preview_raises_when_a_tile_is_refused(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    with (
        httpx.Client(transport=transport) as http_client,
        pytest.raises(RequestFailedError, match="HTTP 403; pass basemap=False"),
    ):
        save_preview(BOUNDARY, tmp_path / "map.png", http_client=http_client)
    assert not (tmp_path / "map.png").exists()


def test_plain_preview_makes_no_request(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        save_preview(BOUNDARY, tmp_path / "plain.png", basemap=False, http_client=http_client)
    assert (tmp_path / "plain.png").read_bytes().startswith(b"\x89PNG")
