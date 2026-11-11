"""Fetch the boundary polygon Google Maps draws for a place.

Public names:
    fetch_boundary, find_place: one-off helpers.
    BoundaryClient, AsyncBoundaryClient: reusable clients.
    Boundary, Place: the returned types.
    MAX_ZOOM: the finest tile zoom that carries boundaries.
    preview.save_preview: draw a boundary to a PNG (needs the preview extra).
    GmapsBoundaryError and its subclasses: PlaceNotFoundError, NoBoundaryError,
        TooManyTilesError, ResponseFormatError, RequestFailedError.
"""

from importlib.metadata import version

from ._boundary import Boundary
from ._places import Place
from ._tiles import MAX_ZOOM
from .client import AsyncBoundaryClient, BoundaryClient, fetch_boundary, find_place
from .errors import (
    GmapsBoundaryError,
    NoBoundaryError,
    PlaceNotFoundError,
    RequestFailedError,
    ResponseFormatError,
    TooManyTilesError,
)

__version__ = version("gmaps-boundary")

__all__ = [
    "MAX_ZOOM",
    "AsyncBoundaryClient",
    "Boundary",
    "BoundaryClient",
    "GmapsBoundaryError",
    "NoBoundaryError",
    "Place",
    "PlaceNotFoundError",
    "RequestFailedError",
    "ResponseFormatError",
    "TooManyTilesError",
    "__version__",
    "fetch_boundary",
    "find_place",
]
