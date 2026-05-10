# Spotify Public-Playlist Ingest

This document describes [`src/stemguessr/spotify.py`](../src/stemguessr/spotify.py) — the layer that turns a public Spotify playlist URL into a list of `Track` objects with direct preview URLs. **No authentication is required.**

## Why no auth

Spotify supports unauthenticated embedding of any public playlist (it is how third-party sites embed Spotify content via iframe). The embed page at

```
https://open.spotify.com/embed/playlist/<id>
```

is server-rendered with Next.js. Its HTML contains a `<script id="__NEXT_DATA__" type="application/json">` element holding the full initial state of the React client, including the playlist's track list. For each track the embed already includes:

| Field | Source |
|-------|--------|
| Spotify track ID | `uri` (split off the `spotify:track:` prefix) |
| Title | `title` |
| Artists (joined string) | `subtitle` |
| Duration in milliseconds | `duration` |
| 30-second MP3 preview URL | `audioPreview.url` (CDN: `p.scdn.co`) |

This is the same data Spotify itself feeds to its web player for unauthenticated visitors, so it is robust under typical CDN behaviour: no rate limits beyond what a normal browsing session would hit, no required token refresh, no signature games.

It does not give us ISRCs (those are on the authenticated Web API only). The pipeline accordingly uses the Spotify track ID as the cache key downstream and does not need ISRC-based lookup at all.

## Public API

```python
from stemguessr.spotify import fetch_playlist_tracks, parse_playlist_id

playlist_id = parse_playlist_id("https://open.spotify.com/playlist/...")
tracks = fetch_playlist_tracks("https://open.spotify.com/playlist/...")
# tracks: list[Track], each with spotify_id, title, artists, duration_ms, preview_url
```

`parse_playlist_id` accepts:

| Form | Example |
|------|---------|
| Bare ID | `37i9dQZF1DXcBWIGoYBM5M` |
| URI | `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M` |
| Web URL | `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M` |
| Web URL with share token | `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123` |
| Internationalised path | `https://open.spotify.com/intl-en/playlist/37i9dQZF1DXcBWIGoYBM5M` |

The 22-character ID is base-62 (alphanumeric, no padding). Inputs whose host is not `spotify.com`, whose path lacks `/playlist/`, or whose extracted ID fails the `^[A-Za-z0-9]{22}$` check raise `SpotifyError`.

## `Track` schema

```python
@dataclass(frozen=True, slots=True)
class Track:
    spotify_id: str        # 22-char Spotify track ID
    isrc: str | None       # always None on the embed path; reserved for future use
    title: str
    artists: tuple[str, ...]
    duration_ms: int
    preview_url: str | None  # https://p.scdn.co/mp3-preview/...
```

`preview_url` may be `None` for tracks Spotify does not serve a preview for (regional restrictions, takedowns); the CLI skips these with a stderr warning.

## Artist-name splitting

Spotify renders the artist list as a single `subtitle` string, e.g. `"Justin Bieber, Nicki Minaj"`. The parser splits on a comma followed by any whitespace (including U+00A0 NBSP, which Spotify uses in some locales). Artists with literal commas in their stage names are not handled — this is best-effort, and the title-only answer matcher in the frontend does not depend on artist parsing.

## Failure modes

A single exception type, `SpotifyError`, is raised for:

| Cause | Where |
|-------|-------|
| Empty / malformed playlist URL or URI | `parse_playlist_id` |
| Embed page returns 4xx (e.g. 404 — playlist private or removed) | `fetch_playlist_tracks` |
| Embed HTML lacks `__NEXT_DATA__` | `_extract_next_data` |
| `__NEXT_DATA__` is not valid JSON | `_extract_next_data` |
| Expected JSON path missing (`props.pageProps.state.data.entity.trackList`) | `fetch_playlist_tracks` |

Network errors (`httpx.RequestError`) are wrapped in `SpotifyError`. Transient retries are not implemented at this layer; the caller (CLI) decides on retry policy.

## Testing

Unit tests in [`tests/test_spotify.py`](../tests/test_spotify.py) use `httpx.MockTransport` to fake the embed page. Coverage:

- URL/URI/bare-ID parsing across valid and invalid forms (17 cases).
- `_extract_next_data`: happy path, missing `<script>` tag, malformed JSON.
- `_track_from_embed_item`: happy path, multi-artist split, NBSP separator, missing/empty `audioPreview`.
- `fetch_playlist_tracks`: happy path, full URL form accepted, 4xx response, missing `trackList` path, missing `__NEXT_DATA__`, request-URL pattern.

Run:

```bash
uv run pytest tests/test_spotify.py -v
```

The latest test report is at [`../tests/reports/phase2_spotify.md`](../tests/reports/phase2_spotify.md).

## References

<span id="ref-isrc">[1]</span> ISO 3901:2019. *Information and documentation — International Standard Recording Code (ISRC).* International Organization for Standardization. [Link](https://www.iso.org/standard/64817.html) — retained as a reference; the embed path does not expose ISRC.

<span id="ref-spotify-embed">[2]</span> Spotify. *Embed widget for playlists.* `https://open.spotify.com/embed/playlist/<id>`.
