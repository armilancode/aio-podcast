"""Asynchronous podcast feed HTTP client."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import aiohttp

from .exceptions import (
    FeedTooLargeError,
    PodcastConnectionError,
    PodcastHTTPError,
    PodcastRedirectError,
    PodcastSSLError,
    PodcastTimeoutError,
)
from .models import Podcast
from .parser import PodcastFeedParser

DEFAULT_MAX_FEED_BYTES = 10 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 64 * 1024


class PodcastClient:
    """Fetch and incrementally parse podcast feeds."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        timeout: aiohttp.ClientTimeout | None = None,
        maximum_feed_bytes: int = DEFAULT_MAX_FEED_BYTES,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize the client with an externally managed session."""
        if maximum_feed_bytes <= 0:
            raise ValueError("maximum_feed_bytes must be positive")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._session = session
        self._timeout = timeout or aiohttp.ClientTimeout(total=20)
        self._maximum_feed_bytes = maximum_feed_bytes
        self._chunk_size = chunk_size
        self._headers = dict(headers or {})

    async def async_fetch(self, url: str) -> Podcast:
        """Fetch and parse one podcast feed URL."""
        try:
            async with self._session.get(
                url,
                allow_redirects=True,
                headers=self._headers,
                timeout=self._timeout,
            ) as response:
                if response.status >= 400:
                    raise PodcastHTTPError(response.status)
                parser = PodcastFeedParser(url, str(response.url))
                total = 0
                async for chunk in response.content.iter_chunked(self._chunk_size):
                    total += len(chunk)
                    if total > self._maximum_feed_bytes:
                        raise FeedTooLargeError(self._maximum_feed_bytes)
                    parser.feed(chunk)
                    await asyncio.sleep(0)
                return parser.close()
        except TimeoutError as err:
            raise PodcastTimeoutError("Podcast feed request timed out") from err
        except aiohttp.ClientSSLError as err:
            raise PodcastSSLError(str(err)) from err
        except aiohttp.TooManyRedirects as err:
            raise PodcastRedirectError("Podcast feed redirects too many times") from err
        except aiohttp.ClientError as err:
            raise PodcastConnectionError(str(err)) from err
