"""Incremental podcast RSS and Atom parser."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final, cast
from urllib.parse import urljoin
from xml.etree import ElementTree

from .exceptions import InvalidFeedError, NoEpisodesError, NoPlayableEpisodesError
from .models import Podcast, PodcastEnclosure, PodcastEpisode

_AUDIO_EXTENSIONS: Final = (".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".wav")
_FORBIDDEN_XML_MARKERS: Final = (b"<!DOCTYPE", b"<!ENTITY")


def _local_name(value: str) -> str:
    """Return a lowercase XML local name."""
    return value.rsplit("}", 1)[-1].lower()


def _namespace(value: str) -> str:
    """Return the namespace URI from an expanded XML name."""
    if value.startswith("{") and "}" in value:
        return value[1 : value.index("}")].lower()
    return ""


def _text(element: ElementTree.Element | None) -> str | None:
    """Return non-empty element text, including nested text nodes."""
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _attribute(element: ElementTree.Element, name: str) -> str | None:
    """Return an attribute by local name."""
    for key, value in element.attrib.items():
        if _local_name(key) == name and value.strip():
            return value.strip()
    return None


def _direct_child(element: ElementTree.Element, *names: str) -> ElementTree.Element | None:
    """Return the first direct child with one of the requested local names."""
    requested = set(names)
    return next((child for child in element if _local_name(child.tag) in requested), None)


def _direct_text(element: ElementTree.Element, *names: str) -> str | None:
    """Return text from the first matching direct child."""
    for name in names:
        value = _text(_direct_child(element, name))
        if value:
            return value
    return None


def _namespaced_text(element: ElementTree.Element, namespace_fragment: str, name: str) -> str | None:
    """Return text from a direct child in a matching namespace."""
    for child in element:
        if _local_name(child.tag) == name and namespace_fragment in _namespace(child.tag):
            value = _text(child)
            if value:
                return value
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse common RSS and Atom dates as timezone-aware UTC datetimes."""
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_to_seconds(value: str | None) -> int | None:
    """Convert Apple podcast durations to seconds."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    try:
        parts = [int(float(part)) for part in stripped.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def _is_audio(url: str, mime_type: str | None) -> bool:
    """Return whether an enclosure is playable podcast audio."""
    if mime_type and mime_type.lower().startswith("audio/"):
        return True
    path = url.lower().split("?", 1)[0]
    return path.endswith(_AUDIO_EXTENSIONS)


def _parse_length(value: str | None) -> int | None:
    """Parse a non-negative enclosure byte length."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _find_enclosure(element: ElementTree.Element, base_url: str) -> PodcastEnclosure | None:
    """Return the first playable RSS, Media RSS, or Atom enclosure."""
    for child in element.iter():
        name = _local_name(child.tag)
        namespace = _namespace(child.tag)
        if name == "enclosure":
            url = _attribute(child, "url") or _attribute(child, "href")
        elif name == "content" and "search.yahoo.com/mrss" in namespace:
            url = _attribute(child, "url")
        elif name == "link" and (_attribute(child, "rel") or "").lower() in {"", "alternate", "enclosure"}:
            url = _attribute(child, "href")
        else:
            continue
        if not url:
            continue
        mime_type = _attribute(child, "type")
        absolute_url = urljoin(base_url, url)
        if not _is_audio(absolute_url, mime_type):
            continue
        return PodcastEnclosure(
            url=absolute_url,
            mime_type=mime_type,
            length=_parse_length(_attribute(child, "length") or _attribute(child, "filesize")),
        )
    return None


def _find_link(element: ElementTree.Element, base_url: str) -> str | None:
    """Return a feed or episode website URL."""
    fallback: str | None = None
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        rel = (_attribute(child, "rel") or "alternate").lower()
        if rel == "enclosure":
            continue
        value = _attribute(child, "href") or _text(child)
        if not value:
            continue
        absolute_url = urljoin(base_url, value)
        if rel == "alternate":
            return absolute_url
        fallback = fallback or absolute_url
    return fallback


def _find_image(element: ElementTree.Element, base_url: str) -> str | None:
    """Return common RSS, Apple podcast, Atom, or Media RSS artwork."""
    for child in element:
        name = _local_name(child.tag)
        namespace = _namespace(child.tag)
        value: str | None = None
        if name == "image" and "itunes" in namespace:
            value = _attribute(child, "href")
        elif name == "image" and not namespace:
            value = _direct_text(child, "url") or _text(child)
        elif name in {"thumbnail", "content"} and "search.yahoo.com/mrss" in namespace:
            value = _attribute(child, "url")
        elif name in {"logo", "icon"}:
            value = _text(child)
        if value:
            return urljoin(base_url, value)
    return None


class PodcastFeedParser:
    """Incrementally parse one podcast RSS or Atom document."""

    def __init__(self, source_url: str, canonical_url: str | None = None) -> None:
        """Initialize an incremental parser."""
        self._source_url = source_url
        self._canonical_url = canonical_url or source_url
        self._parser: ElementTree.XMLPullParser[ElementTree.Element[str]] = ElementTree.XMLPullParser(
            events=("start", "end")
        )
        self._stack: list[ElementTree.Element] = []
        self._format: str | None = None
        self._title: str | None = None
        self._description: str | None = None
        self._author: str | None = None
        self._website_url: str | None = None
        self._artwork_url: str | None = None
        self._entry_count = 0
        self._episodes: list[PodcastEpisode] = []
        self._security_tail = b""

    def feed(self, data: bytes) -> None:
        """Feed one XML byte chunk into the parser."""
        scan = (self._security_tail + data).upper()
        if any(marker in scan for marker in _FORBIDDEN_XML_MARKERS):
            raise InvalidFeedError("DTD and entity declarations are not supported")
        self._security_tail = scan[-16:]
        try:
            self._parser.feed(data)
            self._process_events()
        except ElementTree.ParseError as err:
            raise InvalidFeedError(f"Podcast feed is not well-formed XML: {err}") from err

    def close(self) -> Podcast:
        """Finish parsing and return a normalized podcast."""
        try:
            self._parser.close()
            self._process_events()
        except ElementTree.ParseError as err:
            raise InvalidFeedError(f"Podcast feed is not well-formed XML: {err}") from err
        if self._format is None:
            raise InvalidFeedError("Document is not an RSS or Atom feed")
        if self._entry_count == 0:
            raise NoEpisodesError("Podcast feed contains no episodes")
        if not self._episodes:
            raise NoPlayableEpisodesError("Podcast feed contains no playable audio enclosures")
        return Podcast(
            source_url=self._source_url,
            canonical_url=self._canonical_url,
            title=self._title or "Untitled podcast",
            episodes=tuple(self._episodes),
            description=self._description,
            author=self._author,
            website_url=self._website_url,
            artwork_url=self._artwork_url,
        )

    def _process_events(self) -> None:
        events = cast(
            "Iterator[tuple[str, ElementTree.Element[str]]]",
            self._parser.read_events(),
        )
        for event, element in events:
            if event == "start":
                self._stack.append(element)
                if len(self._stack) == 1:
                    root_name = _local_name(element.tag)
                    if root_name == "rss":
                        self._format = "rss"
                    elif root_name == "feed":
                        self._format = "atom"
                continue

            parent = self._stack[-2] if len(self._stack) > 1 else None
            name = _local_name(element.tag)
            parent_name = _local_name(parent.tag) if parent is not None else None

            is_feed_element = (
                self._format == "rss" and parent_name == "channel" and name != "item"
            ) or (
                self._format == "atom" and parent_name == "feed" and name != "entry"
            )
            if is_feed_element:
                self._consume_feed_element(element)
            elif (self._format == "rss" and name == "item") or (self._format == "atom" and name == "entry"):
                self._consume_episode(element)
                element.clear()

            self._stack.pop()

    def _consume_feed_element(self, element: ElementTree.Element) -> None:
        name = _local_name(element.tag)
        namespace = _namespace(element.tag)
        value = _text(element)
        if name == "title" and value and not self._title:
            self._title = value
        elif name in {"description", "subtitle", "summary"} and value and not self._description:
            self._description = value
        elif name == "author" and not self._author:
            self._author = _direct_text(element, "name") or value
        elif (
            (name == "creator" and "purl.org/dc" in namespace) or name == "publisher"
        ) and value and not self._author:
            self._author = value
        elif name == "link" and not self._website_url:
            href = _attribute(element, "href")
            rel = (_attribute(element, "rel") or "alternate").lower()
            if rel == "alternate" and (href or value):
                self._website_url = urljoin(self._canonical_url, href or value or "")
        elif name in {"image", "thumbnail", "logo", "icon", "content"} and not self._artwork_url:
            wrapper = ElementTree.Element("wrapper")
            wrapper.append(element)
            self._artwork_url = _find_image(wrapper, self._canonical_url)
        if name == "author" and "itunes" in namespace and value:
            self._author = value

    def _consume_episode(self, element: ElementTree.Element) -> None:
        self._entry_count += 1
        enclosure = _find_enclosure(element, self._canonical_url)
        if enclosure is None:
            return
        episode_artwork = _find_image(element, self._canonical_url) or self._artwork_url
        published = _parse_datetime(
            _direct_text(element, "pubdate", "published", "updated", "date")
        )
        self._episodes.append(
            PodcastEpisode(
                title=_direct_text(element, "title") or "Untitled episode",
                enclosure=enclosure,
                guid=_direct_text(element, "guid", "id"),
                description=_direct_text(element, "summary", "description", "subtitle", "content"),
                published=published,
                duration_seconds=_duration_to_seconds(
                    _namespaced_text(element, "itunes", "duration") or _direct_text(element, "duration")
                ),
                artwork_url=episode_artwork,
                website_url=_find_link(element, self._canonical_url),
                explicit=_namespaced_text(element, "itunes", "explicit") or _direct_text(element, "explicit"),
                season=_namespaced_text(element, "itunes", "season") or _direct_text(element, "season"),
                episode_number=_namespaced_text(element, "itunes", "episode") or _direct_text(element, "episode"),
            )
        )


def parse_podcast_feed(data: bytes, source_url: str, canonical_url: str | None = None) -> Podcast:
    """Parse one complete podcast feed document."""
    parser = PodcastFeedParser(source_url, canonical_url)
    parser.feed(data)
    return parser.close()
