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


ISSUES_URL = "https://github.com/kujjwal02/gmaps-boundary/issues"


class ResponseFormatError(GmapsBoundaryError):
    """A Google response did not have the expected shape. The format may have changed.

    ``detail`` says what was wrong. The message adds where to report it.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(
            f"{detail}. Google may have changed its format. "
            f"Check for a newer gmaps-boundary, then report it at {ISSUES_URL}"
        )


class RequestFailedError(GmapsBoundaryError):
    """An HTTP request failed after every retry."""
