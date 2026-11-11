"""Draw a boundary to a PNG, over a Google Maps or OpenStreetMap basemap.

Needs matplotlib: ``pip install 'gmaps-boundary[preview]'``.
"""

from __future__ import annotations

import io
import math
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, get_args

import httpx

from ._boundary import Boundary
from .errors import GmapsBoundaryError, RequestFailedError

Basemap = Literal["google", "osm", "none"]
BASEMAPS: tuple[Basemap, ...] = get_args(Basemap)

_PROJECT_URL = "https://github.com/kujjwal02/gmaps-boundary"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
_GOOGLE_TILE_URL = "https://mt1.google.com/vt/lyrs=m&hl=en&scale=2&x={x}&y={y}&z={zoom}"
_OSM_TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
_GOOGLE_ATTRIBUTION = "Map data (C) Google"
_OSM_ATTRIBUTION = "(C) OpenStreetMap contributors"
_MAX_TILE_ZOOM = 19
# A preview stays within this many basemap tiles. The OSM tile usage policy asks for light use.
_MAX_BASEMAP_TILES = 20
_MARGIN_RATIO = 0.08

Frame = tuple[float, float, float, float]


def _validated_basemap(basemap: str) -> Basemap:
    for known in BASEMAPS:
        if basemap == known:
            return known
    raise ValueError(f"basemap: expected one of {', '.join(BASEMAPS)}, got {basemap!r}")


def _tile_position(longitude: float, latitude: float, zoom: int) -> tuple[float, float]:
    """Web Mercator position in fractional tiles at ``zoom``."""
    tiles_per_side = 1 << zoom
    x = (longitude + 180.0) / 360.0 * tiles_per_side
    y = (1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * tiles_per_side
    return x, y


def _frame(boundary: Boundary, zoom: int, aspect: float | None) -> Frame:
    """The drawn area as ``(left, top, right, bottom)`` in fractional tiles, with a margin.

    ``aspect`` is width over height. The frame grows on one axis to reach it.
    """
    west, south, east, north = boundary.bounds
    left, top = _tile_position(west, north, zoom)
    right, bottom = _tile_position(east, south, zoom)
    margin = max(right - left, bottom - top) * _MARGIN_RATIO
    left, top, right, bottom = left - margin, top - margin, right + margin, bottom + margin
    if aspect is not None:
        width, height = right - left, bottom - top
        extra_width = max(height * aspect - width, 0.0)
        extra_height = max(width / aspect - height, 0.0)
        left, right = left - extra_width / 2, right + extra_width / 2
        top, bottom = top - extra_height / 2, bottom + extra_height / 2
    return left, top, right, bottom


def _tile_count(frame: Frame) -> int:
    left, top, right, bottom = frame
    columns = math.floor(right) - math.floor(left) + 1
    rows = math.floor(bottom) - math.floor(top) + 1
    return columns * rows


def _basemap_zoom(boundary: Boundary, aspect: float | None) -> int:
    for zoom in range(_MAX_TILE_ZOOM, 0, -1):
        if _tile_count(_frame(boundary, zoom, aspect)) <= _MAX_BASEMAP_TILES:
            return zoom
    return 0


def _draw_tiles(
    axis: Any, frame: Frame, zoom: int, basemap: Literal["google", "osm"], http: httpx.Client
) -> None:
    from matplotlib.image import imread

    if basemap == "google":
        url_template, image_format = _GOOGLE_TILE_URL, "png"
        client_name = _BROWSER_USER_AGENT
    else:
        url_template, image_format = _OSM_TILE_URL, "png"
        # tile.openstreetmap.org refuses a client that does not name its application.
        client_name = f"gmaps-boundary/{version('gmaps-boundary')} (+{_PROJECT_URL})"
    left, top, right, bottom = frame
    tiles_per_side = 1 << zoom
    for x in range(math.floor(left), math.floor(right) + 1):
        for y in range(max(math.floor(top), 0), min(math.floor(bottom), tiles_per_side - 1) + 1):
            url = url_template.format(zoom=zoom, x=x % tiles_per_side, y=y)
            try:
                response = http.get(url, headers={"User-Agent": client_name})
            except httpx.TransportError as error:
                raise RequestFailedError(f"basemap tile {url} failed: {error}") from error
            if response.status_code != 200:
                raise RequestFailedError(
                    f"basemap tile {url} answered HTTP {response.status_code}; "
                    "pass basemap='none' to draw without a map"
                )
            axis.imshow(
                imread(io.BytesIO(response.content), format=image_format),
                extent=(x, x + 1, y + 1, y),
                interpolation="bilinear",
                zorder=0,
            )


def _draw_outline_only(axis: Any, boundary: Boundary) -> None:
    from matplotlib.ticker import MaxNLocator

    for polygon in getattr(boundary.geometry, "geoms", [boundary.geometry]):
        axis.fill(*polygon.exterior.xy, facecolor=(1.0, 0.0, 0.0, 0.08), edgecolor="red")
        for hole in polygon.interiors:
            axis.fill(*hole.xy, facecolor="white", edgecolor="red")
    axis.set_aspect(1.0 / math.cos(math.radians(boundary.place.latitude)))
    axis.xaxis.set_major_locator(MaxNLocator(5))
    axis.ticklabel_format(useOffset=False, style="plain")
    axis.set_xlabel("longitude")
    axis.set_ylabel("latitude")


def _draw_over_map(
    axis: Any,
    boundary: Boundary,
    basemap: Literal["google", "osm"],
    aspect: float | None,
    http: httpx.Client,
) -> None:
    zoom = _basemap_zoom(boundary, aspect)
    frame = _frame(boundary, zoom, aspect)
    _draw_tiles(axis, frame, zoom, basemap, http)
    for polygon in getattr(boundary.geometry, "geoms", [boundary.geometry]):
        outer = [_tile_position(lng, lat, zoom) for lng, lat in polygon.exterior.coords]
        axis.fill(*zip(*outer, strict=True), facecolor=(0.92, 0.26, 0.21, 0.10), zorder=1)
        for ring in (polygon.exterior, *polygon.interiors):
            positions = [_tile_position(lng, lat, zoom) for lng, lat in ring.coords]
            axis.plot(
                *zip(*positions, strict=True),
                color="#d93025",
                linewidth=2,
                linestyle=(0, (1, 1)),
                zorder=2,
            )
    left, top, right, bottom = frame
    axis.set_xlim(left, right)
    axis.set_ylim(bottom, top)
    axis.set_aspect("equal")
    axis.set_axis_off()
    axis.text(
        0.995,
        0.005,
        _GOOGLE_ATTRIBUTION if basemap == "google" else _OSM_ATTRIBUTION,
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none", "pad": 1.5},
        zorder=3,
    )


def draw_boundary(
    axis: Any,
    boundary: Boundary,
    *,
    basemap: Basemap = "google",
    aspect: float | None = None,
    http_client: httpx.Client | None = None,
) -> None:
    """Draw ``boundary`` on a matplotlib axis.

    Args:
        axis: The matplotlib ``Axes`` to draw on.
        boundary: The boundary to draw.
        basemap: ``"google"`` draws Google Maps road tiles behind the outline, ``"osm"``
            draws OpenStreetMap tiles, ``"none"`` draws the outline on longitude and
            latitude axes with no network use. A map makes up to 20 tile requests.
        aspect: Width over height of the drawn area, for a map. None fits the boundary.
        http_client: Your own httpx client for the basemap tiles.
    """
    basemap = _validated_basemap(basemap)
    if basemap == "none":
        _draw_outline_only(axis, boundary)
    elif http_client is not None:
        _draw_over_map(axis, boundary, basemap, aspect, http_client)
    else:
        with httpx.Client(timeout=20.0) as own_client:
            _draw_over_map(axis, boundary, basemap, aspect, own_client)
    axis.set_title(boundary.place.name or boundary.place.feature_id)


def save_preview(
    boundary: Boundary,
    png_path: str | Path,
    *,
    basemap: Basemap = "google",
    http_client: httpx.Client | None = None,
) -> None:
    """Draw ``boundary`` to a PNG file. See ``draw_boundary`` for the options."""
    basemap = _validated_basemap(basemap)
    try:
        import matplotlib
    except ImportError as error:
        raise GmapsBoundaryError(
            "previews need matplotlib: pip install 'gmaps-boundary[preview]'"
        ) from error
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 8))
    try:
        draw_boundary(axis, boundary, basemap=basemap, http_client=http_client)
        figure.savefig(png_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(figure)
