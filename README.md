# aio-podcast

`aio-podcast` is a typed asynchronous client for podcast RSS and Atom feeds.
It accepts an existing `aiohttp.ClientSession`, parses responses incrementally,
and returns immutable normalized models.

```shell
python -m pip install aio-podcast
```

## Features

- RSS 2.0 and Atom podcast feeds
- Apple Podcasts and Media RSS metadata
- Injected `aiohttp.ClientSession`
- Incremental parsing with configurable response and chunk limits
- Relative enclosure, artwork, and website URL resolution
- Typed exceptions and PEP 561 type information
- DTD and entity declaration rejection

## Usage

```python
import aiohttp

from aiopodcast import PodcastClient


async def load_podcast(url: str) -> None:
    async with aiohttp.ClientSession() as session:
        podcast = await PodcastClient(session).async_fetch(url)
        print(podcast.title)
        for episode in podcast.episodes:
            print(episode.title, episode.enclosure.url)
```

Applications that already manage an `aiohttp.ClientSession` should pass that
session to `PodcastClient`. The client never closes an injected session.

## Requirements

- Python 3.11 or newer
- aiohttp 3.11 or newer

## License

Apache License 2.0
