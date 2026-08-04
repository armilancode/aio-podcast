"""Immutable podcast feed models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PodcastEnclosure:
    """Playable podcast episode enclosure."""

    url: str
    mime_type: str | None = None
    length: int | None = None


@dataclass(frozen=True, slots=True)
class PodcastEpisode:
    """Normalized podcast episode metadata."""

    title: str
    enclosure: PodcastEnclosure
    guid: str | None = None
    description: str | None = None
    published: datetime | None = None
    duration_seconds: int | None = None
    artwork_url: str | None = None
    website_url: str | None = None
    explicit: str | None = None
    season: str | None = None
    episode_number: str | None = None


@dataclass(frozen=True, slots=True)
class Podcast:
    """Normalized podcast feed and its playable episodes."""

    source_url: str
    canonical_url: str
    title: str
    episodes: tuple[PodcastEpisode, ...]
    description: str | None = None
    author: str | None = None
    website_url: str | None = None
    artwork_url: str | None = None
