from __future__ import annotations

import json

import pytest

from gmaps_boundary import Place, PlaceNotFoundError, ResponseFormatError
from gmaps_boundary._places import parse_search_response, search_url

PLACE_URL = (
    "https://www.google.com/maps/place/Indiranagar,+Bengaluru,+Karnataka/"
    "@12.9730599,77.6382116,15z/data=!3m1!4b1!4m6!3m5"
    "!1s0x3bae16a418770391:0xb50f46b826501036!8m2!3d12.9783692!4d77.6408356!16zL20vMDZ5M3Zj"
)


def search_body(hits: list[object]) -> bytes:
    return (")]}'\n" + json.dumps([["query", hits]])).encode()


def hit(feature_id: object, latitude: object, longitude: object) -> list[object]:
    record: list[object] = [None] * 19
    record[9] = [None, None, latitude, longitude]
    record[10] = feature_id
    record[11] = "Indiranagar"
    record[18] = "Indiranagar, Bengaluru, Karnataka"
    return [None] * 14 + [record]


def test_from_url_reads_id_label_point_and_name() -> None:
    place = Place.from_url(PLACE_URL)
    assert place == Place(
        feature_id="0x3bae16a418770391:0xb50f46b826501036",
        latitude=12.9783692,
        longitude=77.6408356,
        name="Indiranagar, Bengaluru, Karnataka",
    )
    assert place.cell_id == 4300399588226302865
    assert place.feature_number == 13046724402246324278


def test_from_url_names_the_missing_part() -> None:
    with pytest.raises(ValueError, match=r"no '!1s0x\.\.:0x\.\.' feature id"):
        Place.from_url("https://maps.app.goo.gl/abc123")
    with pytest.raises(ValueError, match="label point"):
        Place.from_url("https://www.google.com/maps/place/X/data=!1s0x1:0x2")


@pytest.mark.parametrize(
    ("field", "arguments"),
    [
        ("feature_id", {"feature_id": "ChIJkQN3GKQWrjsR", "latitude": 1.0, "longitude": 1.0}),
        ("latitude", {"feature_id": "0x1:0x2", "latitude": 91.0, "longitude": 1.0}),
        ("longitude", {"feature_id": "0x1:0x2", "latitude": 1.0, "longitude": 181.0}),
    ],
)
def test_place_rejects_a_bad_field_by_name(field: str, arguments: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=f"^{field}:"):
        Place(**arguments)  # type: ignore[arg-type]


def test_search_url_encodes_the_query() -> None:
    assert search_url("Indiranagar, Bengaluru", "en", "in") == (
        "https://www.google.com/search?tbm=map&hl=en&gl=in&q=Indiranagar%2C+Bengaluru"
    )


def test_parse_search_response_returns_the_first_place() -> None:
    body = search_body([[None] * 5, hit("0x1:0x2", 12.5, 77.5), hit("0x3:0x4", 1.0, 2.0)])
    assert parse_search_response(body, "q") == Place(
        feature_id="0x1:0x2",
        latitude=12.5,
        longitude=77.5,
        name="Indiranagar",
        address="Indiranagar, Bengaluru, Karnataka",
    )


def test_parse_search_response_raises_not_found_without_a_place_hit() -> None:
    with pytest.raises(PlaceNotFoundError, match="'pizza near me'"):
        parse_search_response(search_body([[None] * 11]), "pizza near me")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'[["q", []]]', "JSON guard prefix"),
        (b")]}'\n{not json", "not JSON"),
        (b")]}'\n[[]]", "no hit list"),
        (search_body([hit("0x1:0x2", None, 77.5)]), "no label point"),
    ],
)
def test_parse_search_response_rejects_an_unexpected_shape(body: bytes, message: str) -> None:
    with pytest.raises(ResponseFormatError, match=message):
        parse_search_response(body, "q")
