# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## 0.1.1 - 2026-11-11

- Previews draw over Google Maps tiles by default. `basemap` is `"google"`, `"osm"` or `"none"`, in `save_preview` and in the command's `--basemap` option. This replaces the boolean `basemap` and `--no-basemap` of 0.1.0.
- `draw_boundary` draws on your own matplotlib axis.
- `ResponseFormatError` messages say where to report a format change.
- Documentation of the tile and search formats in `docs/`.

## 0.1.0 - 2026-11-11

- `fetch_boundary` and `find_place` helpers.
- `BoundaryClient` and `AsyncBoundaryClient` with proxy, retry and locale settings.
- Lookup by place name, Google Maps place URL or `Place`.
- Automatic zoom selection within a tile cap.
- `http_client` option to send requests through your own httpx session.
- `gmaps-boundary` command with GeoJSON output.
- PNG preview over an OpenStreetMap basemap, from the command or `save_preview`.
