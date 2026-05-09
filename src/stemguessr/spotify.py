"""Spotify Web API integration: playlist URL parsing and track listing extraction.

Uses the spotipy library with the OAuth 2.0 Client Credentials flow. No user
OAuth required; public playlist metadata is sufficient for the StemGuessr
ingest pipeline.

Environment variables (read on demand by :func:`get_client`):

    SPOTIFY_CLIENT_ID:     Spotify app client ID
    SPOTIFY_CLIENT_SECRET: Spotify app client secret

Register an application at https://developer.spotify.com/dashboard.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Spotify object IDs are 22-char base-62 (alphanumeric, no padding). This pattern
# applies uniformly to playlists, albums, tracks, and artists.
_PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{22}$")


@dataclass(frozen=True, slots=True)
class Track:
    """Minimal track metadata extracted from Spotify, sufficient for downstream
    ISRC-based preview lookup.

    Attributes:
        spotify_id: 22-char Spotify track ID.
        isrc: International Standard Recording Code; the lookup key for iTunes /
            Deezer preview retrieval (Phase 3). May be None when Spotify omits it.
        title: Track title as Spotify reports it.
        artists: Tuple of artist names in Spotify's billing order.
        duration_ms: Track duration in milliseconds.
    """

    spotify_id: str
    isrc: str | None
    title: str
    artists: tuple[str, ...]
    duration_ms: int


class SpotifyError(RuntimeError):
    """Raised when Spotify API access fails or input is malformed."""


def parse_playlist_id(url_or_uri: str) -> str:
    """Extract the 22-char Spotify playlist ID from a URL or URI.

    Accepted forms (host comparison is case-insensitive)::

        spotify:playlist:<id>
        https://open.spotify.com/playlist/<id>
        https://open.spotify.com/playlist/<id>?si=<share_token>
        https://open.spotify.com/intl-XX/playlist/<id>[?...]

    Args:
        url_or_uri: A string that may carry a playlist identifier.

    Returns:
        The 22-character base-62 playlist ID.

    Raises:
        SpotifyError: If the input does not match any known playlist URL/URI
            form, or the extracted ID fails the base-62 length/charset check.
    """
    s = url_or_uri.strip()
    if not s:
        raise SpotifyError("Empty playlist URL/URI")

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


def get_client(
    client_id: str | None = None,
    client_secret: str | None = None,
) -> spotipy.Spotify:
    """Construct a spotipy client using the Client Credentials flow.

    Falls back to the ``SPOTIFY_CLIENT_ID`` and ``SPOTIFY_CLIENT_SECRET``
    environment variables when arguments are not provided.

    The returned client lazily fetches its access token on first API call;
    construction itself does not contact Spotify, so this function is safe
    to call in offline tests with dummy credentials.

    Raises:
        SpotifyError: If neither argument nor environment variable is set
            for either credential.
    """
    cid = client_id or os.environ.get("SPOTIFY_CLIENT_ID")
    cs = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not cs:
        raise SpotifyError(
            "Spotify credentials not configured. "
            "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment "
            "variables, or pass them explicitly to get_client()."
        )
    auth = SpotifyClientCredentials(client_id=cid, client_secret=cs)
    return spotipy.Spotify(auth_manager=auth)


def _track_from_item(item: dict[str, Any]) -> Track | None:
    """Build a Track from one element of /playlist/{id}/tracks `items`.

    Returns None for null tracks (local files, removed tracks, podcasts), which
    Spotify represents as items with ``track=None`` or ``track.id=None``.
    """
    track = item.get("track")
    if not track or not track.get("id"):
        return None
    external_ids = track.get("external_ids") or {}
    return Track(
        spotify_id=track["id"],
        isrc=external_ids.get("isrc"),
        title=track["name"],
        artists=tuple(a["name"] for a in track.get("artists", [])),
        duration_ms=int(track["duration_ms"]),
    )


def fetch_playlist_tracks(
    client: spotipy.Spotify,
    playlist_id: str,
    *,
    page_size: int = 100,
) -> list[Track]:
    """Fetch all tracks from a Spotify public playlist, paginating through the response.

    Spotify's playlist tracks endpoint returns at most ``page_size`` items per
    call (cap is 100). This function follows the ``next`` link until exhausted.

    Local files, removed tracks, and podcast episodes are silently skipped
    (see :func:`_track_from_item`).

    Args:
        client: Authenticated spotipy client (see :func:`get_client`).
        playlist_id: The 22-char playlist ID (see :func:`parse_playlist_id`).
        page_size: Page size; Spotify caps this at 100. Default 100.

    Returns:
        List of :class:`Track` objects in playlist order.

    Raises:
        spotipy.exceptions.SpotifyException: On API errors. Not caught here;
            the caller decides on retry / abort policy.
    """
    fields = "items(track(id,name,duration_ms,external_ids,artists(name))),next"
    tracks: list[Track] = []
    offset = 0
    while True:
        page = client.playlist_items(
            playlist_id,
            offset=offset,
            limit=page_size,
            fields=fields,
        )
        for item in page.get("items", []):
            track = _track_from_item(item)
            if track is not None:
                tracks.append(track)
        if not page.get("next"):
            break
        offset += page_size
    return tracks
