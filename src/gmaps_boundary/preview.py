"""Draw a boundary to a PNG, over an OpenStreetMap basemap by default.

Needs matplotlib: ``pip install 'gmaps-boundary[preview]'``.
"""

from __future__ import annotations

import io
import math
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from ._boundary import Boundary
from .errors import GmapsBoundaryError, RequestFailedError

_OSM_TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
_OSM_ATTRIBUTION = "(C) OpenStreetMap contributors"
_OSM_MAX_ZOOM = 19
# The OSM tile usage policy asks for light use. A preview stays within this many tiles.
_MAX_BASEMAP_TILES = 20
_MARGIN_RATIO = 0.08
_PROJECT_URL = "https://github.com/kujjwal02/gmaps-boundary"


def _tile_position(longitude: float, latitude: float, zoom: int) -> tuple[float, float]:
    """Web Mercator position in fractional tiles at ``zoom``."""
    tiles_per_side = 1 << zoom
    x = (longitude + 180.0) / 360.0 * tiles_per_side
    y = (1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * tiles_per_side
    return x, y


def _frame(boundary: Boundary, zoom: int) -> tuple[float, float, float, float]:
    """The drawn area as ``(left, top, right, bottom)`` in fractional tiles, with a margin."""
    west, south, east, north = boundary.bounds
    left, top = _tile_position(west, north, zoom)
    right, bottom = _tile_position(east, south, zoom)
    margin = max(right - left, bottom - top) * _MARGIN_RATIO
    return left - margin, top - margin, right + margin, bottom + margin


def _tile_count(frame: tuple[float, float, float, float]) -> int:
    left, top, right, bottom = frame
    columns = math.floor(right) - math.floor(left) + 1
    rows = math.floor(bottom) - math.floor(top) + 1
    return columns * rows


def _basemap_zoom(boundary: Boundary) -> int:
    for zoom in range(_OSM_MAX_ZOOM, 0, -1):
        if _tile_count(_frame(boundary, zoom)) <= _MAX_BASEMAP_TILES:
            return zoom
    return 0


def _draw_basemap(
    axis: Any, frame: tuple[float, float, float, float], zoom: int, http: httpx.Client
) -> None:
    from matplotlib.image import imread

    left, top, right, bottom = frame
    tiles_per_side = 1 << zoom
    for x in range(math.floor(left), math.floor(right) + 1):
        for y in range(max(math.floor(top), 0), min(math.floor(bottom), tiles_per_side - 1) + 1):
            url = _OSM_TILE_URL.format(zoom=zoom, x=x % tiles_per_side, y=y)
            try:
                response = http.get(url)
            except httpx.TransportError as error:
                raise RequestFailedError(f"basemap tile {url} failed: {error}") from error
            if response.status_code != 200:
                raise RequestFailedError(
                    f"basemap tile {url} answered HTTP {response.status_code}; "
                    "pass basemap=False to draw without a map"
                )
            axis.imshow(
                imread(io.BytesIO(response.content), format="png"),
                extent=(x, x + 1, y + 1, y),
                zorder=0,
            )


def save_preview(
    boundary: Boundary,
    png_path: str | Path,
    *,
    basemap: bool = True,
    http_client: httpx.Client | None = None,
) -> None:
    """Draw ``boundary`` to a PNG file.

    Args:
        boundary: The boundary to draw.
        png_path: Where to write the PNG.
        basemap: Draw OpenStreetMap tiles behind the outline. This makes up to 20 requests
            to ``tile.openstreetmap.org``. False draws the outline on longitude and
            latitude axes, with no network use.
        http_client: Your own httpx client for the basemap tiles. It must send a User-Agent
            that names your application, as the OpenStreetMap tile usage policy requires.
    """
    try:
        import matplotlib
    except ImportError as error:
        raise GmapsBoundaryError(
            "previews need matplotlib: pip install 'gmaps-boundary[preview]'"
        ) from error
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    title = boundary.place.name or boundary.place.feature_id
    polygons = list(getattr(boundary.geometry, "geoms", [boundary.geometry]))
    figure, axis = plt.subplots(figsize=(8, 8))
    try:
        if basemap:
            zoom = _basemap_zoom(boundary)
            frame = _frame(boundary, zoom)
            owned_client = None
            if http_client is None:
                client_name = f"gmaps-boundary/{version('gmaps-boundary')} (+{_PROJECT_URL})"
                owned_client = http_client = httpx.Client(
                    headers={"User-Agent": client_name}, timeout=20.0
                )
            try:
                _draw_basemap(axis, frame, zoom, http_client)
            finally:
                if owned_client is not None:
                    owned_client.close()
            for polygon in polygons:
                for ring in (polygon.exterior, *polygon.interiors):
                    positions = [_tile_position(lng, lat, zoom) for lng, lat in ring.coords]
                    axis.plot(*zip(*positions, strict=True), color="red", linewidth=2, zorder=2)
                outer = [_tile_position(lng, lat, zoom) for lng, lat in polygon.exterior.coords]
                axis.fill(*zip(*outer, strict=True), facecolor=(1.0, 0.0, 0.0, 0.08), zorder=1)
            left, top, right, bottom = frame
            axis.set_xlim(left, right)
            axis.set_ylim(bottom, top)
            axis.set_aspect("equal")
            axis.set_axis_off()
            axis.text(
                0.995,
                0.005,
                _OSM_ATTRIBUTION,
                transform=axis.transAxes,
                ha="right",
                va="bottom",
                fontsize=7,
                bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none", "pad": 1.5},
                zorder=3,
            )
        else:
            for polygon in polygons:
                axis.fill(*polygon.exterior.xy, facecolor=(1.0, 0.0, 0.0, 0.08), edgecolor="red")
                for hole in polygon.interiors:
                    axis.fill(*hole.xy, facecolor="white", edgecolor="red")
            axis.set_aspect(1.0 / math.cos(math.radians(boundary.place.latitude)))
            axis.xaxis.set_major_locator(MaxNLocator(5))
            axis.ticklabel_format(useOffset=False, style="plain")
            axis.set_xlabel("longitude")
            axis.set_ylabel("latitude")
        axis.set_title(title)
        figure.savefig(png_path, dpi=120, bbox_inches="tight")
    finally:
        plt.close(figure)
