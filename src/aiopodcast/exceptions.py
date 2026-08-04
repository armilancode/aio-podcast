"""Exceptions raised by aio-podcast."""


class PodcastFeedError(Exception):
    """Base exception for podcast feed failures."""


class InvalidFeedError(PodcastFeedError):
    """Raised when a document is not a supported podcast feed."""


class NoEpisodesError(InvalidFeedError):
    """Raised when a feed contains no episode entries."""


class NoPlayableEpisodesError(InvalidFeedError):
    """Raised when no episode has a playable audio enclosure."""


class FeedTooLargeError(PodcastFeedError):
    """Raised when a feed exceeds the configured response limit."""

    def __init__(self, maximum_bytes: int) -> None:
        super().__init__(f"Podcast feed exceeds the {maximum_bytes}-byte limit")
        self.maximum_bytes = maximum_bytes


class PodcastHTTPError(PodcastFeedError):
    """Raised when a feed endpoint returns an HTTP error status."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Podcast feed server returned HTTP {status}")
        self.status = status


class PodcastConnectionError(PodcastFeedError):
    """Raised when a feed endpoint cannot be reached."""


class PodcastTimeoutError(PodcastConnectionError):
    """Raised when fetching a podcast feed times out."""


class PodcastSSLError(PodcastConnectionError):
    """Raised when TLS validation or negotiation fails."""


class PodcastRedirectError(PodcastConnectionError):
    """Raised when a feed redirects too many times."""
