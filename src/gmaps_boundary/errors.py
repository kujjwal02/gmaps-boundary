"""Errors raised by gmaps-boundary."""

from __future__ import annotations


class GmapsBoundaryError(Exception):
    """Parent of every error this package raises."""


class PlaceNotFoundError(GmapsBoundaryError):
    """Google Maps search returned no place for the query."""


class NoBoundaryError(GmapsBoundaryError):
    """Google Maps draws no boundary for the place, for example a shop or a road."""


class TooManyTilesError(GmapsBoundaryError):
    """The place needs more tile requests than ``max_tiles`` allows at this zoom."""


class ResponseFormatError(GmapsBoundaryError):
    """A Google response did not have the expected shape. The format may have changed."""


class RequestFailedError(GmapsBoundaryError):
    """An HTTP request failed after every retry."""
