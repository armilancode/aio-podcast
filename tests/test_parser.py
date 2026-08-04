"""Tests for incremental podcast feed parsing."""

from datetime import UTC, datetime

import pytest

from aiopodcast import (
    InvalidFeedError,
    NoEpisodesError,
    NoPlayableEpisodesError,
    PodcastFeedParser,
    parse_podcast_feed,
)
from aiopodcast.parser import (
    _duration_to_seconds,
    _parse_datetime,
    _parse_length,
)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Example Podcast</title>
    <link>https://example.com/podcast</link>
    <itunes:author>Example Host</itunes:author>
    <itunes:image href="https://example.com/feed.jpg" />
    <item><title>No Audio</title></item>
    <item>
      <guid>episode-1</guid>
      <title>Episode One</title>
      <description>Episode description</description>
      <pubDate>Thu, 25 Jun 2026 10:00:00 +0000</pubDate>
      <itunes:duration>1:02:03</itunes:duration>
      <itunes:season>2</itunes:season>
      <itunes:episode>7</itunes:episode>
      <itunes:explicit>no</itunes:explicit>
      <enclosure url="/audio/episode-1.mp3" type="audio/mpeg" length="12345" />
    </item>
  </channel>
</rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Podcast</title>
  <subtitle>Atom description</subtitle>
  <author><name>Atom Host</name></author>
  <link rel="alternate" href="/show" />
  <logo>/cover.jpg</logo>
  <entry>
    <id>tag:example.test,2026:episode-1</id>
    <title>Atom Episode</title>
    <summary>Atom summary</summary>
    <published>2026-06-25T10:00:00Z</published>
    <link rel="enclosure" href="/episode.m4a" type="audio/mp4" length="456" />
    <link rel="alternate" href="/episode" />
  </entry>
</feed>"""


def test_parse_rss_podcast() -> None:
    podcast = parse_podcast_feed(RSS, "https://example.com/feed.xml")

    assert podcast.title == "Example Podcast"
    assert podcast.author == "Example Host"
    assert podcast.website_url == "https://example.com/podcast"
    assert podcast.artwork_url == "https://example.com/feed.jpg"
    assert len(podcast.episodes) == 1
    episode = podcast.episodes[0]
    assert episode.guid == "episode-1"
    assert episode.title == "Episode One"
    assert episode.description == "Episode description"
    assert episode.published == datetime(2026, 6, 25, 10, tzinfo=UTC)
    assert episode.duration_seconds == 3723
    assert episode.season == "2"
    assert episode.episode_number == "7"
    assert episode.explicit == "no"
    assert episode.enclosure.url == "https://example.com/audio/episode-1.mp3"
    assert episode.enclosure.mime_type == "audio/mpeg"
    assert episode.enclosure.length == 12345


def test_parse_atom_podcast() -> None:
    podcast = parse_podcast_feed(ATOM, "https://example.test/feed.atom")

    assert podcast.title == "Atom Podcast"
    assert podcast.description == "Atom description"
    assert podcast.author == "Atom Host"
    assert podcast.website_url == "https://example.test/show"
    assert podcast.artwork_url == "https://example.test/cover.jpg"
    episode = podcast.episodes[0]
    assert episode.guid == "tag:example.test,2026:episode-1"
    assert episode.title == "Atom Episode"
    assert episode.enclosure.url == "https://example.test/episode.m4a"
    assert episode.website_url == "https://example.test/episode"


def test_media_rss_audio_and_artwork_fallbacks() -> None:
    document = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
      <title>Media Podcast</title><description>Description</description>
      <image><url>/feed.jpg</url></image>
      <item><title>Media Episode</title><media:thumbnail url="/episode.jpg" />
      <media:content url="/episode.ogg?download=1" fileSize="42" /></item>
    </channel></rss>"""

    podcast = parse_podcast_feed(document, "https://example.test/feed.xml")

    assert podcast.artwork_url == "https://example.test/feed.jpg"
    episode = podcast.episodes[0]
    assert episode.artwork_url == "https://example.test/episode.jpg"
    assert episode.enclosure.url == "https://example.test/episode.ogg?download=1"
    assert episode.enclosure.length == 42


def test_feed_and_episode_fallback_metadata() -> None:
    document = b"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
      <description>Fallback description</description><dc:creator>Publisher</dc:creator>
      <link>https://example.test/show</link>
      <item><link rel="related" href="/related"/><link rel="alternate" />
      <updated>Thu, 25 Jun 2026 10:00:00</updated>
      <enclosure/><enclosure url="/not-audio.bin" type="application/octet-stream" />
      <enclosure href="/episode.wav" length="invalid" /></item>
    </channel></rss>"""

    podcast = parse_podcast_feed(document, "https://example.test/feed.xml")

    assert podcast.title == "Untitled podcast"
    assert podcast.description == "Fallback description"
    assert podcast.author == "Publisher"
    assert podcast.website_url == "https://example.test/show"
    episode = podcast.episodes[0]
    assert episode.title == "Untitled episode"
    assert episode.published == datetime(2026, 6, 25, 10, tzinfo=UTC)
    assert episode.website_url == "https://example.test/related"
    assert episode.enclosure.url == "https://example.test/episode.wav"
    assert episode.enclosure.length is None


def test_date_duration_and_length_edge_cases() -> None:
    assert _parse_datetime(None) is None
    assert _parse_datetime("not a date") is None
    assert _parse_datetime("2026-06-25T10:00:00") == datetime(2026, 6, 25, 10, tzinfo=UTC)
    assert _duration_to_seconds(None) is None
    assert _duration_to_seconds("90") == 90
    assert _duration_to_seconds("02:03") == 123
    assert _duration_to_seconds("bad") is None
    assert _duration_to_seconds("1:2:3:4") is None
    assert _parse_length(None) is None
    assert _parse_length("bad") is None
    assert _parse_length("-1") is None


def test_incremental_chunks_and_canonical_url() -> None:
    parser = PodcastFeedParser("https://old.example/feed.xml", "https://new.example/feed.xml")
    for offset in range(0, len(RSS), 17):
        parser.feed(RSS[offset : offset + 17])

    podcast = parser.close()

    assert podcast.source_url == "https://old.example/feed.xml"
    assert podcast.canonical_url == "https://new.example/feed.xml"
    assert podcast.episodes[0].enclosure.url == "https://new.example/audio/episode-1.mp3"


@pytest.mark.parametrize("marker", [b"<!DOCTYPE rss>", b"<!ENTITY x 'bad'>"])
def test_rejects_dtd_and_entities_across_chunks(marker: bytes) -> None:
    parser = PodcastFeedParser("https://example.test/feed.xml")
    document = b"<rss>" + marker + b"</rss>"

    def feed_chunks() -> None:
        for offset in range(0, len(document), 3):
            parser.feed(document[offset : offset + 3])

    with pytest.raises(InvalidFeedError):
        feed_chunks()


def test_reports_invalid_feed_shapes() -> None:
    with pytest.raises(NoEpisodesError):
        parse_podcast_feed(b"<rss><channel><title>Empty</title></channel></rss>", "https://example.test/feed.xml")
    with pytest.raises(NoPlayableEpisodesError):
        parse_podcast_feed(
            b"<rss><channel><item><title>No audio</title></item></channel></rss>",
            "https://example.test/feed.xml",
        )
    with pytest.raises(InvalidFeedError):
        parse_podcast_feed(b"not xml <", "https://example.test/feed.xml")
    with pytest.raises(InvalidFeedError):
        parse_podcast_feed(b"<html><body /></html>", "https://example.test/feed.xml")

    parser = PodcastFeedParser("https://example.test/feed.xml")
    parser.feed(b"<rss><channel>")
    with pytest.raises(InvalidFeedError):
        parser.close()
