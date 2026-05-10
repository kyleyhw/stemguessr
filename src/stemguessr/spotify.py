"""Spotify public-playlist ingest via the open.spotify.com embed page.

No authentication is required: this module never calls the authenticated
Spotify Web API. Instead, it fetches the public embed page that Spotify
itself uses to display playlists in third-party iframes, parses the
``__NEXT_DATA__`` JSON payload that the page embeds for the React client,
and returns a list of :class:`Track` objects.

A side benefit of this approach: each track in the embed JSON carries a
direct ``audioPreview.url`` to a 30-second MP3 hosted on Spotify's CDN
(``p.scdn.co``). Downstream consumers can download from that URL directly,
avoiding the iTunes / Deezer ISRC-based detour that earlier versions of
this code used. ISRCs are not exposed on this code path; track identity is
keyed by Spotify ID instead.

Public API:

* :func:`parse_playlist_id` — playlist URL/URI → 22-char playlist ID.
* :func:`fetch_playlist_tracks` — playlist URL/URI → list of :class:`Track`.
* :class:`Track` — immutable per-track metadata + preview URL.
* :class:`SpotifyError` — raised for parse / fetch / structural failures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

# Spotify object IDs are 22-char base-62 (alphanumeric, no padding). This pattern
# applies uniformly to playlists, albums, tracks, and artists.
_PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{22}$")

# A modern desktop UA. Without this, Spotify's CDN may return 403.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

EMBED_URL_TEMPLATE = "https://open.spotify.com/embed/playlist/{playlist_id}"
_NEXT_DATA_PATTERN = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Track:
    """Per-track metadata extracted from the Spotify embed page.

    Attributes:
        spotify_id: 22-char Spotify track ID.
        isrc: International Standard Recording Code. Always ``None`` on the
            embed-based path; retained for forwards-compatibility with any
            future authenticated path that does expose it.
        title: Track title as Spotify reports it.
        artists: Tuple of artist names. Spotify's embed concatenates them
            into a single ``subtitle`` string; this module splits on the
            common ``, `` separator to recover individuals (best-effort —
            artists with literal commas in their stage names are not handled).
        duration_ms: Track duration in milliseconds.
        preview_url: Direct URL to a ~30-second MP3 preview hosted on
            Spotify's CDN (``p.scdn.co``). May be ``None`` when Spotify
            does not provide a preview for the track (regional restriction,
            takedown, etc.).
    """

    spotify_id: str
    isrc: str | None
    title: str
    artists: tuple[str, ...]
    duration_ms: int
    preview_url: str | None


class SpotifyError(RuntimeError):
    """Raised when Spotify input is malformed, the embed page cannot be
    fetched, or the embedded JSON's structure does not match expectations.
    """


def parse_playlist_id(url_or_uri: str) -> str:
    """Extract the 22-char Spotify playlist ID from a URL or URI.

    Accepted forms (host comparison is case-insensitive)::

        spotify:playlist:<id>
        https://open.spotify.com/playlist/<id>
        https://open.spotify.com/playlist/<id>?si=<share_token>
        https://open.spotify.com/intl-XX/playlist/<id>[?...]

    Raises:
        SpotifyError: Input does not match a known playlist URL/URI form,
            or the extracted ID fails the base-62 length/charset check.
    """
    s = url_or_uri.strip()
    if not s:
        raise SpotifyError("Empty playlist URL/URI")

    # Bare ID — accept it directly (the pattern doubles as a validity check).
    if _PLAYLIST_ID_PATTERN.match(s):
        return s

    if s.startswith("spotify:playlist:"):
        playlist_id = s[len("spotify:playlist:") :]
    else:
        parsed = urlparse(s)
        host = parsed.netloc.lower()
        if "spotify.com" not in host:
            raise SpotifyError(f"Not a Spotify URL: {url_or_uri!r}")
        parts = [p for p in parsed.path.split("/") if p]
        if "playlist" not in parts:
            raise SpotifyError(
                f"Not a playlist URL (no /playlist/ in path): {url_or_uri!r}"
            )
        idx = parts.index("playlist")
        if idx + 1 >= len(parts):
            raise SpotifyError(
                f"Playlist URL missing ID after /playlist/: {url_or_uri!r}"
            )
        playlist_id = parts[idx + 1]

    if not _PLAYLIST_ID_PATTERN.match(playlist_id):
        raise SpotifyError(f"Invalid Spotify playlist ID format: {playlist_id!r}")

    return playlist_id


def fetch_playlist_tracks(
    playlist_url_or_id: str,
    *,
    client: httpx.Client | None = None,
) -> list[Track]:
    """Fetch all tracks of a public Spotify playlist via the embed page.

    Args:
        playlist_url_or_id: Any URL/URI form accepted by
            :func:`parse_playlist_id`, or a bare playlist ID.
        client: Optional pre-built ``httpx.Client``; an internal one is
            created and disposed otherwise.

    Returns:
        A list of :class:`Track` objects in playlist order. Tracks for which
        the embed page lacked an ``audioPreview.url`` still appear, with
        ``preview_url=None`` — the caller decides how to handle them.

    Raises:
        SpotifyError: ID parse failure, HTTP fetch failure, ``__NEXT_DATA__``
            absent from the page, or expected JSON path missing.
    """
    playlist_id = parse_playlist_id(playlist_url_or_id)
    url = EMBED_URL_TEMPLATE.format(playlist_id=playlist_id)

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": _BROWSER_USER_AGENT},
            follow_redirects=True,
            timeout=10.0,
        )
    try:
        response = client.get(url)
    except httpx.HTTPError as e:
        raise SpotifyError(f"Failed to fetch embed page: {e}") from e
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise SpotifyError(
            f"Embed page returned HTTP {response.status_code}; "
            "playlist may be private or removed."
        )

    data = _extract_next_data(response.text)
    try:
        track_items = data["props"]["pageProps"]["state"]["data"]["entity"]["trackList"]
    except (KeyError, TypeError) as e:
        raise SpotifyError(
            "Could not locate trackList in embed JSON; Spotify's page "
            "structure may have changed."
        ) from e

    return [_track_from_embed_item(item) for item in track_items]


def _extract_next_data(html: str) -> dict[str, Any]:
    """Extract the ``__NEXT_DATA__`` JSON blob from a Spotify embed page.

    Spotify's embed pages render with Next.js; the React client receives its
    initial state from a single inline ``<script id="__NEXT_DATA__">`` tag,
    which is exactly what we want.
    """
    match = _NEXT_DATA_PATTERN.search(html)
    if not match:
        raise SpotifyError(
            "Embed page did not contain __NEXT_DATA__ script tag; "
            "Spotify may have changed the page structure."
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise SpotifyError(f"__NEXT_DATA__ was not valid JSON: {e}") from e


def _track_from_embed_item(item: dict[str, Any]) -> Track:
    """Build a :class:`Track` from one element of ``trackList``."""
    uri = item.get("uri", "")
    spotify_id = uri.split(":")[-1] if uri else ""

    subtitle = item.get("subtitle", "") or ""
    # Spotify renders artist lists as "Artist 1, Artist 2" (note: NBSP after
    # the comma in some locales). Split on a comma followed by any whitespace.
    artists = tuple(a.strip() for a in re.split(r",[\s ]*", subtitle) if a.strip())

    audio_preview = item.get("audioPreview") or {}
    preview_url = audio_preview.get("url")

    return Track(
        spotify_id=spotify_id,
        isrc=None,
        title=item.get("title", "") or "",
        artists=artists,
        duration_ms=int(item.get("duration", 0) or 0),
        preview_url=preview_url,
    )
