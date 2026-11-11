# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## 0.1.0 - 2026-11-11

- `fetch_boundary` and `find_place` helpers.
- `BoundaryClient` and `AsyncBoundaryClient` with proxy, retry and locale settings.
- Lookup by place name, Google Maps place URL or `Place`.
- Automatic zoom selection within a tile cap.
- `http_client` option to send requests through your own httpx session.
- `gmaps-boundary` command with GeoJSON output.
- PNG preview over an OpenStreetMap basemap, from the command or `save_preview`.
