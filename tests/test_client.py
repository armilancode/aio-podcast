"""Tests for the asynchronous podcast client."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace, TracebackType
from typing import Self
from unittest.mock import AsyncMock

import aiohttp
import pytest
from yarl import URL

from aiopodcast import (
    FeedTooLargeError,
    PodcastClient,
    PodcastConnectionError,
    PodcastHTTPError,
    PodcastRedirectError,
    PodcastSSLError,
    PodcastTimeoutError,
)

from .test_parser import RSS


class Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class Response(AbstractAsyncContextManager["Response"]):
    def __init__(self, chunks: list[bytes], status: int = 200) -> None:
        self.content = Content(chunks)
        self.status = status
        self.url = URL("https://final.example/feed.xml")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, object]] = []

    def get(self, url: str, **kwargs: object) -> Response:
        self.calls.append((url, kwargs))
        return self.response


class RaisingSession:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def get(self, _url: str, **_kwargs: object) -> Response:
        raise self.error


async def test_fetches_with_injected_session() -> None:
    session = Session(Response([RSS[:200], RSS[200:]]))
    client = PodcastClient(session, headers={"User-Agent": "test"})  # type: ignore[arg-type]

    podcast = await client.async_fetch("https://example.test/feed.xml")

    assert podcast.canonical_url == "https://final.example/feed.xml"
    assert session.calls[0][0] == "https://example.test/feed.xml"


async def test_http_and_size_errors() -> None:
    http_client = PodcastClient(Session(Response([], status=500)))  # type: ignore[arg-type]
    with pytest.raises(PodcastHTTPError) as http_error:
        await http_client.async_fetch("https://example.test/feed.xml")
    assert http_error.value.status == 500

    size_client = PodcastClient(Session(Response([b"abcd"])), maximum_feed_bytes=3)  # type: ignore[arg-type]
    with pytest.raises(FeedTooLargeError):
        await size_client.async_fetch("https://example.test/feed.xml")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), PodcastTimeoutError),
        (
            aiohttp.ClientSSLError(
                connection_key=SimpleNamespace(ssl=True, host="example.test", port=443),
                os_error=OSError("TLS failed"),
            ),
            PodcastSSLError,
        ),
        (aiohttp.TooManyRedirects(None, ()), PodcastRedirectError),
        (aiohttp.ClientError("offline"), PodcastConnectionError),
    ],
)
async def test_maps_connection_errors(error: Exception, expected: type[Exception]) -> None:
    client = PodcastClient(RaisingSession(error))  # type: ignore[arg-type]

    with pytest.raises(expected):
        await client.async_fetch("https://example.test/feed.xml")


async def test_yields_between_buffered_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("aiopodcast.client.asyncio.sleep", sleep)
    session = Session(Response([RSS[:100], RSS[100:300], RSS[300:]]))

    await PodcastClient(session).async_fetch("https://example.test/feed.xml")  # type: ignore[arg-type]

    assert sleep.await_count == 3


def test_client_rejects_invalid_limits() -> None:
    session = Session(Response([]))
    with pytest.raises(ValueError, match="maximum_feed_bytes"):
        PodcastClient(session, maximum_feed_bytes=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="chunk_size"):
        PodcastClient(session, chunk_size=0)  # type: ignore[arg-type]
