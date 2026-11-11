"""The public ``Boundary`` type."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely import MultiPolygon, Polygon
from shapely.geometry import mapping

from ._places import Place
from ._tiles import TILE_EXTENT

_EQUATOR_LENGTH_M = 40_075_016.686

PolygonalGeometry = Polygon | MultiPolygon


@dataclass(frozen=True)
class Boundary:
    """The boundary Google Maps draws for a place.

    ``geometry`` is a shapely geometry in WGS 84, with x as longitude and y as latitude.
    ``zoom`` is the tile zoom the boundary was read at. A higher zoom has more vertices.
    """

    place: Place
    zoom: int
    geometry: PolygonalGeometry

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(west, south, east, north)`` in degrees."""
        west, south, east, north = self.geometry.bounds
        return west, south, east, north

    @property
    def resolution_m(self) -> float:
        """The size of one coordinate step at this zoom and latitude, in metres."""
        metres_per_tile = _EQUATOR_LENGTH_M * math.cos(math.radians(self.place.latitude))
        return metres_per_tile / ((1 << self.zoom) * TILE_EXTENT)

    @property
    def __geo_interface__(self) -> dict[str, Any]:
        return self.to_geojson()

    def to_geojson(self) -> dict[str, Any]:
        """Return a GeoJSON Feature. Its properties describe the place."""
        return {
            "type": "Feature",
            "properties": {
                "name": self.place.name,
                "address": self.place.address,
                "feature_id": self.place.feature_id,
                "label_latitude": self.place.latitude,
                "label_longitude": self.place.longitude,
                "zoom": self.zoom,
            },
            "geometry": mapping(self.geometry),
        }
