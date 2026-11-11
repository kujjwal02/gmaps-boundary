"""Draw the README gallery: a grid of boundaries over Google Maps.

Usage: uv run python scripts/draw_gallery.py docs/gallery.png
"""

from __future__ import annotations

import asyncio
import io
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

from gmaps_boundary import AsyncBoundaryClient, Boundary
from gmaps_boundary.preview import draw_boundary

# Query -> caption. The set covers a locality, a borough, a postal code, a city and a ward.
PLACES = {
    "Indiranagar, Bengaluru": "Indiranagar, Bengaluru (locality)",
    "Manhattan, New York": "Manhattan, New York (borough)",
    "Bandra West, Mumbai": "Bandra West, Mumbai (locality)",
    "Shibuya City, Tokyo": "Shibuya, Tokyo (ward)",
    "Paris, France": "Paris (city)",
    "560038": "560038, Bengaluru (postal code)",
}
COLUMNS = 3
CELL_ASPECT = 1.0


async def fetch_all() -> list[Boundary]:
    async with AsyncBoundaryClient(concurrency=8) as client:
        return [await client.fetch_boundary(query) for query in PLACES]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    boundaries = asyncio.run(fetch_all())
    rows = -(-len(boundaries) // COLUMNS)
    figure, axes = plt.subplots(rows, COLUMNS, figsize=(4.6 * COLUMNS, 4.9 * rows))
    for axis, boundary, caption in zip(axes.flat, boundaries, PLACES.values(), strict=True):
        draw_boundary(axis, boundary, basemap="google", aspect=CELL_ASPECT)
        axis.set_title(caption, fontsize=11)
        print(f"{caption}: {boundary.geometry.geom_type}, zoom {boundary.zoom}")
    figure.tight_layout()
    rendered = io.BytesIO()
    figure.savefig(rendered, dpi=110, format="png")
    plt.close(figure)
    # 256 colours keep the README image under 1 MB.
    Image.open(rendered).convert("RGB").quantize(256).save(sys.argv[1], optimize=True)


if __name__ == "__main__":
    main()
