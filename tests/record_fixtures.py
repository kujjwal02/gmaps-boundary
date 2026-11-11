"""Record live Google responses into tests/fixtures. Run: uv run python tests/record_fixtures.py"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from gmaps_boundary import BoundaryClient, GmapsBoundaryError

FIXTURES = Path(__file__).parent / "fixtures"

# Scenario name -> (query, zoom). Each scenario is replayed by tests/test_client.py.
SCENARIOS: dict[str, tuple[str, int | None]] = {
    "locality": ("Indiranagar, Bengaluru", None),
    "postal_code": ("560038", 16),
    "no_boundary": ("The Rameshwaram Cafe Indiranagar", None),
    "not_found": ("zzqqxxnonexistentplace123", None),
}


class RecordingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self._live = httpx.HTTPTransport()
        self.bodies: dict[str, str] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._live.handle_request(request)
        response.read()
        self.bodies[str(request.url)] = base64.b64encode(response.content).decode("ascii")
        return response


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for scenario, (query, zoom) in SCENARIOS.items():
        transport = RecordingTransport()
        with BoundaryClient(transport=transport) as client:
            try:
                client.fetch_boundary(query, zoom=zoom)
            except GmapsBoundaryError as error:
                print(f"{scenario}: {type(error).__name__}")
        (FIXTURES / f"{scenario}.json").write_text(json.dumps(transport.bodies, indent=0) + "\n")
        print(f"{scenario}: {len(transport.bodies)} responses")


if __name__ == "__main__":
    main()
