"""Checks against the real Google endpoints. Run with: uv run pytest -m live"""

from __future__ import annotations

import pytest

from gmaps_boundary import NoBoundaryError, fetch_boundary

pytestmark = pytest.mark.live


def test_live_locality_matches_the_recorded_bounds() -> None:
    boundary = fetch_boundary("Indiranagar, Bengaluru")
    assert boundary.zoom == 17
    assert boundary.bounds == pytest.approx(
        (77.6285361, 12.9604117, 77.6478871, 12.9857080), abs=1e-4
    )


def test_live_point_of_interest_has_no_boundary() -> None:
    with pytest.raises(NoBoundaryError):
        fetch_boundary("The Rameshwaram Cafe Indiranagar")
