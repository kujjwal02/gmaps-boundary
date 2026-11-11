# gmaps-boundary

Fetch the boundary polygon that Google Maps draws for a locality, city or postal code, as GeoJSON.

When you search for an area on Google Maps, the map outlines it with a red dotted line. This library reads that outline from the map's vector tiles and returns it as a polygon. It needs no API key and no browser.

![Boundaries of Indiranagar, Manhattan, Bandra West, Shibuya, Paris and postal code 560038, drawn over Google Maps](https://raw.githubusercontent.com/kujjwal02/gmaps-boundary/v0.1.1/docs/gallery.png)

Each panel is the polygon this library returned, drawn with `gmaps_boundary.preview`.

## Install

```bash
pip install gmaps-boundary
```

Python 3.10 or newer. Dependencies: `httpx`, `shapely`, `numpy`.

## Use it

```python
from gmaps_boundary import fetch_boundary

boundary = fetch_boundary("Indiranagar, Bengaluru")

boundary.place.name  # 'Indiranagar'
boundary.geometry  # shapely Polygon in WGS 84 (x = longitude, y = latitude)
boundary.bounds  # (west, south, east, north)
boundary.zoom  # 17
boundary.resolution_m  # 0.07, the size of one coordinate step in metres
boundary.to_geojson()  # GeoJSON Feature as a dict
```

`fetch_boundary` accepts any of these:

- a place name: `"Indiranagar, Bengaluru"`, `"560038"`, `"Manhattan, New York"`
- a full Google Maps place URL, the one that contains `!1s0x...:0x...`
- a `Place` object, from `find_place` or built by hand

`Boundary` implements `__geo_interface__`, so GeoPandas and other libraries accept it directly:

```python
import geopandas

frame = geopandas.GeoDataFrame.from_features([boundary.to_geojson()], crs="EPSG:4326")
```

### Many places

Reuse one client. It keeps connections open and applies the same settings to every request.

```python
from gmaps_boundary import BoundaryClient

with BoundaryClient(proxy="http://user:pass@host:8080", request_delay_s=0.2) as client:
    for name in ["Indiranagar, Bengaluru", "Koramangala, Bengaluru"]:
        boundary = client.fetch_boundary(name)
```

### Your own HTTP session

Pass your own `httpx.Client` to control cookies, headers, proxies, timeouts and connection limits. The boundary client sends every request through it and never closes it.

```python
import httpx
from gmaps_boundary import BoundaryClient

session = httpx.Client(
    headers={"User-Agent": "Mozilla/5.0 ..."},
    cookies={"NID": "..."},
    proxy="http://user:pass@host:8080",
    timeout=30.0,
)
with BoundaryClient(http_client=session) as client:
    boundary = client.fetch_boundary("Indiranagar, Bengaluru")
session.close()
```

`AsyncBoundaryClient` takes an `httpx.AsyncClient` the same way. The library's own client sends a browser User-Agent. A session you pass sends whatever you set on it. `http_client` cannot be combined with `proxy`, `timeout_s`, `user_agent` or `transport`; set those on the session.

### Async

`AsyncBoundaryClient` fetches tiles concurrently. A locality takes about 6 seconds with `concurrency=8`, against about 25 seconds for the sync client.

```python
import asyncio
from gmaps_boundary import AsyncBoundaryClient


async def main() -> None:
    async with AsyncBoundaryClient(concurrency=8) as client:
        boundary = await client.fetch_boundary("Koramangala, Bengaluru")


asyncio.run(main())
```

### Command line

```bash
gmaps-boundary "Indiranagar, Bengaluru" -o indiranagar.geojson
gmaps-boundary "560038" --zoom 16 --indent 2 > pincode.geojson
gmaps-boundary "Manhattan, New York" -o manhattan.geojson --preview manhattan.png
```

`--preview` draws the boundary over a map and needs `pip install 'gmaps-boundary[preview]'`. `--basemap` picks the map: `google` (default), `osm`, or `none` for the outline alone with no extra request. Run `gmaps-boundary --help` for every option.

The same drawing is available from Python:

```python
from gmaps_boundary.preview import draw_boundary, save_preview

save_preview(boundary, "indiranagar.png")  # over Google Maps
save_preview(boundary, "indiranagar.png", basemap="osm")  # over OpenStreetMap
save_preview(boundary, "outline.png", basemap="none")  # outline only
draw_boundary(axis, boundary)  # on your own matplotlib axis
```

A map uses at most 20 tiles per image. Google tiles: Map data (C) Google. OpenStreetMap tiles: (C) OpenStreetMap contributors.

## Name lookup

A name goes to Google Maps search, and the library takes the place Google opens for it.

- A name that matches nothing, or a category search such as `"cafes in Indiranagar"`, raises `PlaceNotFoundError`.
- An ambiguous name resolves to Google's top pick, which depends on the region of your IP address. `"Springfield"` can resolve to a landmark instead of a city. Add the city, state or country to the name, and check `boundary.place.address`.
- A name that resolves to a place without a boundary, such as a shop or a road, raises `NoBoundaryError`.
- To check a name before you fetch, call `find_place(name)`. It makes one request and returns the `Place`.

## Zoom and accuracy

Coordinates come from Google's tiles as integers, 4096 steps per tile side. A higher zoom means smaller steps and more vertices.

| zoom | step at the equator | typical use |
|---|---|---|
| 17 | 0.07 m | localities, postal codes |
| 15 | 0.30 m | large districts |
| 14 | 0.60 m | cities |
| 12 | 2.4 m | regions |

Zoom 17 is the finest zoom that carries boundaries. With `zoom=None`, the default, the library picks the finest zoom that fits `max_tiles` (default 500 tile requests per pass). Pass `zoom=` to fix it, or raise `max_tiles` for more detail on a large place.

For Indiranagar, the zoom 17 polygon has 214 vertices. Its bounds match the viewport Google Maps itself uses for the place to within 0.2 m.

## Errors

Every error is a subclass of `GmapsBoundaryError`.

| error | meaning |
|---|---|
| `PlaceNotFoundError` | The name matches no single place. Try a more specific name. |
| `NoBoundaryError` | Google Maps draws no boundary for the place, for example a shop or a road. |
| `TooManyTilesError` | The place does not fit `max_tiles` at the requested zoom. |
| `ResponseFormatError` | A response had an unexpected shape. Google may have changed the format. |
| `RequestFailedError` | A request failed after every retry. |

## How it works

1. A name is resolved to a place through Google Maps search. This gives the feature id and the label point.
2. Google Maps highlights a place through a vector tile layer named `spotlit`. Each tile carries a mask polygon that covers everything outside the place.
3. The library reads the outline at a coarse zoom first. That pass sizes the job and tells the fine pass which tiles to fetch.
4. For each fine tile, the place part is the tile square minus the mask. The parts are merged into one polygon and converted to longitude and latitude.

The [documentation](https://github.com/kujjwal02/gmaps-boundary/tree/main/docs) has the details, with diagrams:

- [How it works](https://github.com/kujjwal02/gmaps-boundary/blob/main/docs/how-it-works.md)
- [Tile format](https://github.com/kujjwal02/gmaps-boundary/blob/main/docs/tile-format.md)
- [Search format](https://github.com/kujjwal02/gmaps-boundary/blob/main/docs/search-format.md)
- [Findings](https://github.com/kujjwal02/gmaps-boundary/blob/main/docs/findings.md)

## If Google changes its format

This library reads undocumented endpoints, and Google can change them at any time. When that happens the library raises `ResponseFormatError`.

Please [open an issue](https://github.com/kujjwal02/gmaps-boundary/issues/new?template=format-change.yml) when:

- you get a `ResponseFormatError`, or
- a polygon does not match the red dotted line that Google Maps shows for the place.

Include the library version, the query, the zoom and the full error message. The guide [Investigating a format change](https://github.com/kujjwal02/gmaps-boundary/blob/main/docs/investigating-format-changes.md) shows how to find what changed, if you want to send a fix.

## Limits

- The tile and search formats are undocumented. See "If Google changes its format" above.
- A place made of separate pieces is returned as a `MultiPolygon`. A piece that lies more than about 10 km from the label point and does not touch the rest can be missed.
- Short `maps.app.goo.gl` links are not accepted. Open the link and copy the full URL.
- The boundary is what Google Maps displays. It is not an official administrative boundary.

## Terms of use

This library is not affiliated with Google. It reads undocumented endpoints, which the Google Maps Platform Terms of Service do not permit for all uses. You are responsible for how you use it and for the data you collect. Keep the request rate low.

## Development

```bash
uv sync
uv run pytest             # offline, replays recorded responses
uv run pytest -m live     # calls Google
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python tests/record_fixtures.py   # refresh the recorded responses
uv run python scripts/draw_gallery.py docs/gallery.png   # redraw the README image
```

The README image URL names a release tag, so a published page keeps its image. Change the tag in that URL when you cut a release.

## License

MIT
