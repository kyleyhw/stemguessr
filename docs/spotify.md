# Spotify Ingest Module

This document describes the Spotify Web API integration in [`src/stemguessr/spotify.py`](../src/stemguessr/spotify.py). It covers the authentication model, URL/URI parsing, track-listing extraction, error model, and rate-limit considerations.

## Purpose

Given a Spotify *public* playlist URL, produce a list of tracks with the metadata required by downstream stages of the StemGuessr pipeline. The critical field is each track's **ISRC** (International Standard Recording Code [[1]](#ref-isrc)), used as the lookup key for preview retrieval in Phase 3.

Spotify itself does not expose raw audio. This module never asks for it; it only retrieves metadata.

## Authentication: Client Credentials flow

For public-playlist read access, Spotify supports the OAuth 2.0 *Client Credentials* grant [[2]](#ref-rfc6749) — a server-to-server flow requiring only an application's `client_id` and `client_secret`, with no end-user login. The flow exchanges those credentials for a short-lived access token (default 1 hour), which the SDK refreshes automatically.

Concretely:

1. Register an application at <https://developer.spotify.com/dashboard>.
2. Set environment variables before running ingest:

    ```bash
    export SPOTIFY_CLIENT_ID="..."
    export SPOTIFY_CLIENT_SECRET="..."
    ```

3. The `get_client()` helper constructs a `spotipy.Spotify` instance using these credentials. Construction is offline; the token is fetched lazily on first API call.

This flow is **insufficient** for accessing user-private playlists, user libraries, or playback control. Those would require the Authorization Code flow with user login, which StemGuessr deliberately does not implement — public playlists are the input contract.

## Playlist URL parsing

Spotify exposes playlists in several URL forms; the parser accepts all of these and rejects everything else:

| Form | Example |
|------|---------|
| URI | `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M` |
| Web URL | `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M` |
| Web URL with share token | `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123` |
| Internationalised path | `https://open.spotify.com/intl-en/playlist/37i9dQZF1DXcBWIGoYBM5M` |

The 22-character ID is base-62 (alphanumeric, no padding). The parser validates length and charset with the regex `^[A-Za-z0-9]{22}$`. Inputs whose host is not `spotify.com` (case-insensitive substring match), whose path lacks `/playlist/`, or whose extracted ID fails the format check raise `SpotifyError`.

## Track listing extraction

`fetch_playlist_tracks(client, playlist_id)` retrieves all tracks in playlist order, paginating through Spotify's `playlist_items` endpoint at the maximum page size of 100. The endpoint is requested with a `fields` mask that returns only the data we need:

```
items(track(id,name,duration_ms,external_ids,artists(name))),next
```

This minimisation reduces payload size and protects against schema changes in fields we do not consume.

Returned `Track` objects are immutable (`@dataclass(frozen=True, slots=True)`) and carry:

- `spotify_id` — Spotify track ID for traceability.
- `isrc` — the lookup key for Phase 3; `None` when Spotify omits it.
- `title` — track title.
- `artists` — tuple of artist names in Spotify's billing order.
- `duration_ms` — duration in milliseconds.

Three classes of items are silently skipped during extraction:

1. **Local files** added to the playlist by the owner — Spotify returns `track=None`.
2. **Removed tracks** — typically `track.id=None`.
3. **Podcast episodes** — same shape as removed tracks under the `fields` mask.

A track with `isrc=None` is still returned; downstream lookup (Phase 3) decides how to handle the miss (warn-and-skip rather than abort).

## Error model

A single exception type, `SpotifyError`, is raised for:

- Empty / malformed playlist URLs / URIs.
- Missing or partial credentials when calling `get_client()`.

Network and HTTP errors during `fetch_playlist_tracks` propagate as `spotipy.exceptions.SpotifyException` and are not caught at this layer; the caller (CLI, Phase 6) decides on retry / abort policy.

## Rate limits

Spotify's public Web API enforces dynamic per-application rate limits (typically a few hundred requests per minute, varying by endpoint and account tier). For a single playlist of fewer than 500 tracks, ingestion makes at most 5 paginated calls — well below any limit. spotipy retries on `429 Too Many Requests` automatically with exponential backoff, so no extra logic is required at this layer.

## Testing

Unit tests in [`tests/test_spotify.py`](../tests/test_spotify.py) cover URL/URI parsing across valid and invalid forms, credential resolution (explicit > env > raise), pagination, null-track handling, and missing-ISRC tolerance. All tests mock the `spotipy.Spotify` client; no network access is required to run the suite.

Run the tests:

```bash
uv run pytest tests/test_spotify.py -v
```

The latest test report is at [`../tests/reports/phase2_spotify.md`](../tests/reports/phase2_spotify.md).

## References

<span id="ref-isrc">[1]</span> ISO 3901:2019. *Information and documentation — International Standard Recording Code (ISRC).* International Organization for Standardization. [Link](https://www.iso.org/standard/64817.html)

<span id="ref-rfc6749">[2]</span> Hardt, D. (Ed.). (2012). *The OAuth 2.0 Authorization Framework* (RFC 6749). Internet Engineering Task Force. [Link](https://datatracker.ietf.org/doc/html/rfc6749)

<span id="ref-spotify-playlist">[3]</span> Spotify. *Web API Reference: Get Playlist Items.* [Link](https://developer.spotify.com/documentation/web-api/reference/get-playlists-tracks)
