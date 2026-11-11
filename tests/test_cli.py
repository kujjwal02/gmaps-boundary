from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import gmaps_boundary.cli as cli_module
from gmaps_boundary import BoundaryClient

from .conftest import ReplayFactory


@pytest.fixture
def replayed_cli(replay: ReplayFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI's client at recorded responses, chosen by the query text."""
    scenarios = {"Indiranagar, Bengaluru": "locality", "zzqqxxnonexistentplace123": "not_found"}

    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request before a scenario was chosen: {request.url}")

    class ReplayedClient(BoundaryClient):
        def __init__(self, **options: object) -> None:
            super().__init__(transport=httpx.MockTransport(respond), request_delay_s=0.0)

        def fetch_boundary(self, query, *, zoom=None, max_tiles=500):  # type: ignore[no-untyped-def]
            self._http = httpx.Client(transport=replay(scenarios[query]))
            return super().fetch_boundary(query, zoom=zoom, max_tiles=max_tiles)

    monkeypatch.setattr(cli_module, "BoundaryClient", ReplayedClient)


@pytest.mark.usefixtures("replayed_cli")
def test_cli_prints_geojson_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_module.main(["Indiranagar, Bengaluru"]) == 0
    captured = capsys.readouterr()
    feature = json.loads(captured.out)
    assert feature["properties"]["name"] == "Indiranagar"
    assert feature["geometry"]["type"] == "Polygon"
    assert captured.err.startswith("Indiranagar: Polygon, zoom 17, about 0.07 m per step")


@pytest.mark.usefixtures("replayed_cli")
def test_cli_writes_the_file_and_the_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    geojson_path, png_path = tmp_path / "out.geojson", tmp_path / "out.png"
    status = cli_module.main(
        [
            "Indiranagar, Bengaluru",
            "-o",
            str(geojson_path),
            "--preview",
            str(png_path),
            "--no-basemap",
        ]
    )
    assert status == 0
    assert capsys.readouterr().out == ""
    assert json.loads(geojson_path.read_text())["type"] == "Feature"
    assert png_path.read_bytes().startswith(b"\x89PNG")


@pytest.mark.usefixtures("replayed_cli")
def test_cli_reports_an_error_and_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_module.main(["zzqqxxnonexistentplace123"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gmaps-boundary: no single place matches")
