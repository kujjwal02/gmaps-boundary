from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

ReplayFactory = Callable[[str], httpx.MockTransport]


@pytest.fixture
def replay() -> ReplayFactory:
    """Return a transport factory that replays one recorded scenario and counts requests."""

    def transport_for(scenario: str) -> httpx.MockTransport:
        recorded: dict[str, str] = json.loads((FIXTURES / f"{scenario}.json").read_text())

        def respond(request: httpx.Request) -> httpx.Response:
            body = recorded.get(str(request.url))
            if body is None:
                return httpx.Response(404, text=f"not recorded: {request.url}")
            return httpx.Response(200, content=base64.b64decode(body))

        return httpx.MockTransport(respond)

    return transport_for
