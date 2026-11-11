# Documentation

These pages record how Google Maps delivers place boundaries and how this library reads them. Google documents none of it. Everything here was observed on the dates given in each page.

| page | what it covers |
|---|---|
| [How it works](how-it-works.md) | The request plan from a place name to a polygon. |
| [Tile format](tile-format.md) | The `spotlit` vector tile request and its wire format. |
| [Search format](search-format.md) | The search request that resolves a name to a place. |
| [Findings](findings.md) | Measurements, the layers that hold no boundary, and known limits. |
| [Investigating a format change](investigating-format-changes.md) | What to do when the library raises `ResponseFormatError`. |

If Google changes a format, [open an issue](https://github.com/kujjwal02/gmaps-boundary/issues/new?template=format-change.yml).
