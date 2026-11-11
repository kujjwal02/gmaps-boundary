"""Sync and async clients that fetch place boundaries from Google Maps."""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import TypeVar

import httpx

from ._boundary import Boundary
from ._places import Place
from ._steps import FetchOptions, PlaceQuery, Steps, boundary_steps, place_steps
from .errors import RequestFailedError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
DEFAULT_MAX_TILES = 500

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_FIRST_RETRY_DELAY_S = 0.5

_DEFAULT_TIMEOUT_S = 20.0

ReturnValue = TypeVar("ReturnValue")


def _reject_connection_options(
    proxy: str | None, timeout_s: float, user_agent: str, transport: object
) -> None:
    """A caller-owned HTTP client carries its own connection settings, so reject ours."""
    conflicts = {
        "proxy": proxy is not None,
        "timeout_s": timeout_s != _DEFAULT_TIMEOUT_S,
        "user_agent": user_agent != DEFAULT_USER_AGENT,
        "transport": transport is not None,
    }
    for option, is_set in conflicts.items():
        if is_set:
            raise ValueError(f"{option}: set it on http_client instead when you pass http_client")


def _validated_attempts(max_retries: int) -> int:
    if max_retries < 0:
        raise ValueError(f"max_retries: expected 0 or more, got {max_retries}")
    return max_retries + 1


def _retry_delay_s(attempt: int) -> float:
    return float(_FIRST_RETRY_DELAY_S * 2**attempt)


def _body_or_none(response: httpx.Response) -> bytes | None:
    """Return the body of a good response, None for a retryable one, and raise otherwise."""
    if response.status_code == 200:
        return response.content
    if response.status_code in _RETRYABLE_STATUS_CODES:
        return None
    raise RequestFailedError(
        f"Google answered HTTP {response.status_code} for {response.request.url.path[:60]}"
    )


def _exhausted(url: str, attempts: int, cause: str) -> RequestFailedError:
    path = httpx.URL(url).path[:60]
    return RequestFailedError(f"request for {path} failed after {attempts} attempts: {cause}")


class BoundaryClient:
    """Fetch place boundaries with blocking HTTP.

    Args:
        proxy: Proxy URL for every request, for example ``"http://user:pass@host:8080"``.
        timeout_s: Timeout for one request, in seconds.
        request_delay_s: Pause after each request, in seconds. Keeps the request rate low.
        max_retries: Retries per request on HTTP 429, HTTP 5xx and transport errors.
        language: Google ``hl`` language code for place names.
        region: Google ``gl`` region code. Google shows disputed borders per region.
        user_agent: The User-Agent header to send.
        transport: A custom httpx transport. Tests use it to replay recorded responses.
        http_client: Your own httpx client, with your cookies, headers, proxy and timeouts.
            The boundary client sends every request through it and never closes it.
            It cannot be combined with ``proxy``, ``timeout_s``, ``user_agent`` or ``transport``.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        request_delay_s: float = 0.1,
        max_retries: int = 3,
        language: str = "en",
        region: str = "us",
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._attempts = _validated_attempts(max_retries)
        self._request_delay_s = request_delay_s
        self._language = language
        self._region = region
        self._owns_http_client = http_client is None
        if http_client is None:
            http_client = httpx.Client(
                headers={"User-Agent": user_agent},
                timeout=timeout_s,
                proxy=proxy,
                transport=transport,
            )
        else:
            _reject_connection_options(proxy, timeout_s, user_agent, transport)
        self._http = http_client

    def __enter__(self) -> BoundaryClient:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client, unless the caller passed their own."""
        if self._owns_http_client:
            self._http.close()

    def find_place(self, query: str) -> Place:
        """Resolve a place name, or a Google Maps place URL, to a ``Place``."""
        return self._run(place_steps(query, self._language, self._region))

    def fetch_boundary(
        self, query: PlaceQuery, *, zoom: int | None = None, max_tiles: int = DEFAULT_MAX_TILES
    ) -> Boundary:
        """Fetch the boundary of a place.

        Args:
            query: A place name, a full Google Maps place URL, or a ``Place``.
            zoom: Tile zoom to read at, 0 to 17. None picks the finest zoom that fits
                ``max_tiles``.
            max_tiles: Cap on tile requests per pass.

        Raises:
            PlaceNotFoundError: The name matches no single place.
            NoBoundaryError: Google Maps draws no boundary for the place.
            TooManyTilesError: The place does not fit ``max_tiles`` at ``zoom``.
            ResponseFormatError: A response had an unexpected shape.
            RequestFailedError: A request failed after every retry.
        """
        options = FetchOptions(
            zoom=zoom,
            max_tiles=max_tiles,
            language=self._language,
            region=self._region,
            batch_size=1,
        )
        return self._run(boundary_steps(query, options))

    def _run(self, steps: Steps[ReturnValue]) -> ReturnValue:
        try:
            urls = next(steps)
            while True:
                urls = steps.send([self._get(url) for url in urls])
        except StopIteration as finished:
            value: ReturnValue = finished.value
            return value

    def _get(self, url: str) -> bytes:
        cause = "no attempt made"
        for attempt in range(self._attempts):
            try:
                body = _body_or_none(self._http.get(url))
            except httpx.TransportError as error:
                cause = f"{type(error).__name__}: {error}"
            else:
                if body is not None:
                    time.sleep(self._request_delay_s)
                    return body
                cause = "retryable HTTP status"
            if attempt + 1 < self._attempts:
                time.sleep(_retry_delay_s(attempt))
        raise _exhausted(url, self._attempts, cause)


class AsyncBoundaryClient:
    """Fetch place boundaries with asyncio. Tile requests run concurrently.

    Args:
        concurrency: Tile requests in flight at once.
        proxy: Proxy URL for every request, for example ``"http://user:pass@host:8080"``.
        timeout_s: Timeout for one request, in seconds.
        max_retries: Retries per request on HTTP 429, HTTP 5xx and transport errors.
        language: Google ``hl`` language code for place names.
        region: Google ``gl`` region code. Google shows disputed borders per region.
        user_agent: The User-Agent header to send.
        transport: A custom httpx transport. Tests use it to replay recorded responses.
        http_client: Your own httpx client, with your cookies, headers, proxy and timeouts.
            The boundary client sends every request through it and never closes it.
            It cannot be combined with ``proxy``, ``timeout_s``, ``user_agent`` or ``transport``.
    """

    def __init__(
        self,
        *,
        concurrency: int = 4,
        proxy: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = 3,
        language: str = "en",
        region: str = "us",
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency: expected at least 1, got {concurrency}")
        self._attempts = _validated_attempts(max_retries)
        self._concurrency = concurrency
        self._language = language
        self._region = region
        self._owns_http_client = http_client is None
        if http_client is None:
            http_client = httpx.AsyncClient(
                headers={"User-Agent": user_agent},
                timeout=timeout_s,
                proxy=proxy,
                transport=transport,
            )
        else:
            _reject_connection_options(proxy, timeout_s, user_agent, transport)
        self._http = http_client

    async def __aenter__(self) -> AsyncBoundaryClient:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client, unless the caller passed their own."""
        if self._owns_http_client:
            await self._http.aclose()

    async def find_place(self, query: str) -> Place:
        """Resolve a place name, or a Google Maps place URL, to a ``Place``."""
        return await self._run(place_steps(query, self._language, self._region))

    async def fetch_boundary(
        self, query: PlaceQuery, *, zoom: int | None = None, max_tiles: int = DEFAULT_MAX_TILES
    ) -> Boundary:
        """Fetch the boundary of a place. See ``BoundaryClient.fetch_boundary``."""
        options = FetchOptions(
            zoom=zoom,
            max_tiles=max_tiles,
            language=self._language,
            region=self._region,
            batch_size=self._concurrency,
        )
        return await self._run(boundary_steps(query, options))

    async def _run(self, steps: Steps[ReturnValue]) -> ReturnValue:
        try:
            urls = next(steps)
            while True:
                bodies = await asyncio.gather(*(self._get(url) for url in urls))
                urls = steps.send(list(bodies))
        except StopIteration as finished:
            value: ReturnValue = finished.value
            return value

    async def _get(self, url: str) -> bytes:
        cause = "no attempt made"
        for attempt in range(self._attempts):
            try:
                body = _body_or_none(await self._http.get(url))
            except httpx.TransportError as error:
                cause = f"{type(error).__name__}: {error}"
            else:
                if body is not None:
                    return body
                cause = "retryable HTTP status"
            if attempt + 1 < self._attempts:
                await asyncio.sleep(_retry_delay_s(attempt))
        raise _exhausted(url, self._attempts, cause)


def find_place(
    query: str,
    *,
    language: str = "en",
    region: str = "us",
    http_client: httpx.Client | None = None,
) -> Place:
    """Resolve a place name to a ``Place`` with a one-off client."""
    with BoundaryClient(language=language, region=region, http_client=http_client) as client:
        return client.find_place(query)


def fetch_boundary(
    query: PlaceQuery,
    *,
    zoom: int | None = None,
    max_tiles: int = DEFAULT_MAX_TILES,
    proxy: str | None = None,
    language: str = "en",
    region: str = "us",
    http_client: httpx.Client | None = None,
) -> Boundary:
    """Fetch the boundary of a place with a one-off client.

    ``query`` is a place name, a full Google Maps place URL, or a ``Place``.
    Use ``BoundaryClient`` to reuse connections across many places.
    """
    with BoundaryClient(
        proxy=proxy, language=language, region=region, http_client=http_client
    ) as client:
        return client.fetch_boundary(query, zoom=zoom, max_tiles=max_tiles)
