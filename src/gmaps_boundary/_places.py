"""Places: the public ``Place`` type, place URL parsing and search response parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from .errors import PlaceNotFoundError, ResponseFormatError

_SEARCH_URL = "https://www.google.com/search"
_FEATURE_ID_PATTERN = re.compile(r"0x([0-9a-f]{1,16}):0x([0-9a-f]{1,16})")
_URL_FEATURE_ID_PATTERN = re.compile(r"!1s(0x[0-9a-f]{1,16}:0x[0-9a-f]{1,16})")
_URL_LABEL_POINT_PATTERN = re.compile(r"!3d(-?[0-9.]+)!4d(-?[0-9.]+)")
_URL_NAME_PATTERN = re.compile(r"/maps/place/([^/@]+)")
_JSON_GUARD = ")]}'"

# Positions inside one search hit. Google sends positional JSON arrays.
_HIT_RECORD_INDEX = 14
_RECORD_POINT_INDEX = 9
_RECORD_FEATURE_ID_INDEX = 10
_RECORD_NAME_INDEX = 11
_RECORD_ADDRESS_INDEX = 18
_POINT_LATITUDE_INDEX = 2
_POINT_LONGITUDE_INDEX = 3


@dataclass(frozen=True)
class Place:
    """A Google Maps place.

    ``feature_id`` is the ``0x..:0x..`` pair found in Google Maps place URLs.
    The label point is where Google Maps puts the place name on the map.
    """

    feature_id: str
    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None

    def __post_init__(self) -> None:
        if _FEATURE_ID_PATTERN.fullmatch(self.feature_id) is None:
            raise ValueError(f"feature_id: expected '0x<hex>:0x<hex>', got {self.feature_id!r}")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude: expected -90 to 90, got {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude: expected -180 to 180, got {self.longitude}")

    @classmethod
    def from_url(cls, url: str) -> Place:
        """Read a place from a full Google Maps place URL.

        The URL must carry ``!1s0x..:0x..`` and ``!3d<lat>!4d<lng>``. That is the URL
        the browser shows after a place opens. Short ``maps.app.goo.gl`` links do not.
        """
        feature_id = _URL_FEATURE_ID_PATTERN.search(url)
        if feature_id is None:
            raise ValueError("url: no '!1s0x..:0x..' feature id found; pass the full place URL")
        label_point = _URL_LABEL_POINT_PATTERN.search(url)
        if label_point is None:
            raise ValueError(
                "url: no '!3d<lat>!4d<lng>' label point found; pass the full place URL"
            )
        name = _URL_NAME_PATTERN.search(url)
        return cls(
            feature_id=feature_id.group(1),
            latitude=float(label_point.group(1)),
            longitude=float(label_point.group(2)),
            name=name.group(1).replace("+", " ") if name else None,
        )

    @property
    def cell_id(self) -> int:
        """The first half of the feature id, as the decimal the tile request needs."""
        return int(self.feature_id.split(":")[0], 16)

    @property
    def feature_number(self) -> int:
        """The second half of the feature id, as the decimal the tile request needs."""
        return int(self.feature_id.split(":")[1], 16)


def search_url(query: str, language: str, region: str) -> str:
    return f"{_SEARCH_URL}?{urlencode({'tbm': 'map', 'hl': language, 'gl': region, 'q': query})}"


def _element(sequence: object, index: int) -> object:
    """Return ``sequence[index]``, or None when the array is too short or not an array."""
    if isinstance(sequence, list) and len(sequence) > index:
        return sequence[index]
    return None


def _optional_text(record: object, index: int) -> str | None:
    text = _element(record, index)
    return text if isinstance(text, str) else None


def parse_search_response(body: bytes, query: str) -> Place:
    """Return the first place of a Google Maps search response."""
    text = body.decode("utf-8", errors="replace")
    if not text.startswith(_JSON_GUARD):
        raise ResponseFormatError("search: response does not start with the JSON guard prefix")
    try:
        payload = json.loads(text[len(_JSON_GUARD) :])
    except json.JSONDecodeError as error:
        raise ResponseFormatError(f"search: response is not JSON: {error}") from error
    hits = _element(_element(payload, 0), 1)
    if not isinstance(hits, list):
        raise ResponseFormatError("search: response has no hit list")
    for hit in hits:
        record = _element(hit, _HIT_RECORD_INDEX)
        feature_id = _element(record, _RECORD_FEATURE_ID_INDEX)
        if not isinstance(feature_id, str):
            continue
        point = _element(record, _RECORD_POINT_INDEX)
        latitude = _element(point, _POINT_LATITUDE_INDEX)
        longitude = _element(point, _POINT_LONGITUDE_INDEX)
        if not isinstance(latitude, float) or not isinstance(longitude, float):
            raise ResponseFormatError(f"search: place {feature_id} has no label point")
        return Place(
            feature_id=feature_id,
            latitude=latitude,
            longitude=longitude,
            name=_optional_text(record, _RECORD_NAME_INDEX),
            address=_optional_text(record, _RECORD_ADDRESS_INDEX),
        )
    raise PlaceNotFoundError(f"no single place matches {query!r}; try a more specific name")
