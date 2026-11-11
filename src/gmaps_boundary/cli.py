"""The ``gmaps-boundary`` command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ._tiles import MAX_ZOOM
from .client import DEFAULT_MAX_TILES, BoundaryClient
from .errors import GmapsBoundaryError
from .preview import BASEMAPS, save_preview


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmaps-boundary",
        description="Fetch the boundary Google Maps draws for a place, as a GeoJSON Feature.",
    )
    parser.add_argument("query", help="place name, or a full Google Maps place URL")
    parser.add_argument(
        "-o", "--out", type=Path, default=None, help="GeoJSON file to write (default: stdout)"
    )
    parser.add_argument(
        "--zoom",
        type=int,
        default=None,
        help=f"tile zoom, 0 to {MAX_ZOOM} (default: the finest that fits --max-tiles)",
    )
    parser.add_argument(
        "--max-tiles",
        type=int,
        default=DEFAULT_MAX_TILES,
        help=f"cap on tile requests per pass (default: {DEFAULT_MAX_TILES})",
    )
    parser.add_argument("--proxy", default=None, help="proxy URL for every request")
    parser.add_argument("--language", default="en", help="Google hl language code (default: en)")
    parser.add_argument("--region", default="us", help="Google gl region code (default: us)")
    parser.add_argument("--indent", type=int, default=None, help="indent the GeoJSON by N spaces")
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="also draw the boundary over a map to this PNG (needs gmaps-boundary[preview])",
    )
    parser.add_argument(
        "--basemap",
        choices=BASEMAPS,
        default="google",
        help="map behind the preview (default: google)",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        with BoundaryClient(
            proxy=options.proxy, language=options.language, region=options.region
        ) as client:
            boundary = client.fetch_boundary(
                options.query, zoom=options.zoom, max_tiles=options.max_tiles
            )
        if options.preview is not None:
            save_preview(boundary, options.preview, basemap=options.basemap)
    except (GmapsBoundaryError, ValueError) as error:
        print(f"gmaps-boundary: {error}", file=sys.stderr)
        return 1
    geojson = json.dumps(boundary.to_geojson(), indent=options.indent, ensure_ascii=False)
    if options.out is None:
        print(geojson)
    else:
        options.out.write_text(geojson + "\n", encoding="utf-8")
    west, south, east, north = boundary.bounds
    print(
        f"{boundary.place.name or boundary.place.feature_id}: {boundary.geometry.geom_type}, "
        f"zoom {boundary.zoom}, about {boundary.resolution_m:.2f} m per step, "
        f"bounds {south:.6f},{west:.6f} to {north:.6f},{east:.6f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
