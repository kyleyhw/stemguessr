"""Tests for stemguessr.spotify module.

All tests run offline. Spotify is mocked at the spotipy.Spotify boundary;
no network access is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from stemguessr.spotify import (
    SpotifyError,
    Track,
    fetch_playlist_tracks,
    get_client,
    parse_playlist_id,
)

# Spotify "Today's Top Hits" playlist ID; serves as a 22-char base-62 example.
# Used solely for its valid-format properties; no actual API call is made in tests.
VALID_ID = "37i9dQZF1DXcBWIGoYBM5M"


class TestParsePlaylistId:
    """Verifies parse_playlist_id over the known acceptable URL/URI forms,
    and SpotifyError on every malformed shape we have observed in the wild
    or constructed adversarially.
    """

    @pytest.mark.parametrize(
        "url",
        [
            f"spotify:playlist:{VALID_ID}",
            f"https://open.spotify.com/playlist/{VALID_ID}",
            f"https://open.spotify.com/playlist/{VALID_ID}?si=abc123def456",
            f"https://open.spotify.com/intl-en/playlist/{VALID_ID}",
            f"https://open.spotify.com/intl-en/playlist/{VALID_ID}?si=xyz",
            f"http://open.spotify.com/playlist/{VALID_ID}",
            f"  https://open.spotify.com/playlist/{VALID_ID}  ",
        ],
    )
    def test_valid_forms_extract_id(self, url: str) -> None:
        assert parse_playlist_id(url) == VALID_ID

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "not a url at all",
            "https://example.com/playlist/" + "a" * 22,
            "https://open.spotify.com/album/" + VALID_ID,
            "https://open.spotify.com/playlist/",
            "spotify:track:" + VALID_ID,
            "spotify:playlist:short",
            "spotify:playlist:" + VALID_ID + "extra",
            "spotify:playlist:" + "!" * 22,  # bad charset
        ],
    )
    def test_invalid_forms_raise(self, bad: str) -> None:
        with pytest.raises(SpotifyError):
            parse_playlist_id(bad)


class TestGetClient:
    """Credential resolution: explicit args > env vars; missing both raises."""

    def test_explicit_args_construct_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
        client = get_client(client_id="explicit_id", client_secret="explicit_secret")
        assert client.auth_manager is not None

    def test_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env_secret")
        client = get_client()
        assert client.auth_manager is not None

    def test_missing_credentials_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
        with pytest.raises(SpotifyError, match="credentials not configured"):
            get_client()

    def test_partial_credentials_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "only_id")
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
        with pytest.raises(SpotifyError):
            get_client()


def _make_item(
    track_id: str,
    title: str,
    artists: list[str],
    duration_ms: int = 200_000,
    isrc: str | None = "USABC1234567",
) -> dict[str, Any]:
    """Construct a fake /playlist_items response item shaped like Spotify's."""
    external_ids = {"isrc": isrc} if isrc is not None else {}
    return {
        "track": {
            "id": track_id,
            "name": title,
            "duration_ms": duration_ms,
            "external_ids": external_ids,
            "artists": [{"name": a} for a in artists],
        }
    }


class TestFetchPlaylistTracks:
    """Pagination, null-track handling, missing-ISRC tolerance.

    All tests use a MagicMock client; no network access.
    """

    def test_single_page(self) -> None:
        client = MagicMock()
        client.playlist_items.return_value = {
            "items": [
                _make_item("id1", "Track 1", ["Artist A"]),
                _make_item("id2", "Track 2", ["Artist B", "Artist C"]),
            ],
            "next": None,
        }
        tracks = fetch_playlist_tracks(client, VALID_ID)
        assert len(tracks) == 2
        assert tracks[0] == Track(
            spotify_id="id1",
            isrc="USABC1234567",
            title="Track 1",
            artists=("Artist A",),
            duration_ms=200_000,
        )
        assert tracks[1].artists == ("Artist B", "Artist C")
        assert client.playlist_items.call_count == 1

    def test_pagination_follows_next(self) -> None:
        client = MagicMock()
        client.playlist_items.side_effect = [
            {
                "items": [_make_item("id1", "Track 1", ["A"])],
                "next": ("https://api.spotify.com/v1/playlists/.../tracks?offset=1"),
            },
            {
                "items": [_make_item("id2", "Track 2", ["B"])],
                "next": None,
            },
        ]
        tracks = fetch_playlist_tracks(client, VALID_ID, page_size=1)
        assert [t.spotify_id for t in tracks] == ["id1", "id2"]
        assert client.playlist_items.call_count == 2

    def test_null_tracks_skipped(self) -> None:
        """Local files and removed tracks appear as null in playlist responses;
        they must be silently dropped rather than crashing the ingest run.
        """
        client = MagicMock()
        client.playlist_items.return_value = {
            "items": [
                {"track": None},  # local file
                _make_item("id1", "Track 1", ["A"]),
                {"track": {"id": None}},  # malformed / removed
            ],
            "next": None,
        }
        tracks = fetch_playlist_tracks(client, VALID_ID)
        assert len(tracks) == 1
        assert tracks[0].spotify_id == "id1"

    def test_missing_isrc_tolerated(self) -> None:
        """Tracks without ISRC are still returned with isrc=None; downstream
        lookup will skip them with a warning rather than aborting ingest.
        """
        client = MagicMock()
        client.playlist_items.return_value = {
            "items": [_make_item("id1", "Track 1", ["A"], isrc=None)],
            "next": None,
        }
        tracks = fetch_playlist_tracks(client, VALID_ID)
        assert tracks[0].isrc is None
