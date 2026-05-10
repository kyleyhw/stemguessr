"""Tests for stemguessr.spotify module — embed-based no-auth ingest.

All tests run offline. The Spotify embed page is faked via httpx.MockTransport;
no real network access is performed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from stemguessr.spotify import (
    EMBED_URL_TEMPLATE,
    SpotifyError,
    Track,
    _extract_next_data,
    _track_from_embed_item,
    fetch_playlist_tracks,
    parse_playlist_id,
)

# "Today's Top Hits" playlist ID. Used as a 22-char base-62 example only;
# tests never make a real API call.
VALID_ID = "37i9dQZF1DXcBWIGoYBM5M"


# ============================================================
# parse_playlist_id
# ============================================================


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
            "spotify:playlist:" + "!" * 22,
        ],
    )
    def test_invalid_forms_raise(self, bad: str) -> None:
        with pytest.raises(SpotifyError):
            parse_playlist_id(bad)


# ============================================================
# _extract_next_data
# ============================================================


def _wrap_next_data(payload: dict[str, Any]) -> str:
    """Build a minimal HTML page with __NEXT_DATA__ holding ``payload``."""
    body = json.dumps(payload)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{body}</script></body></html>'


class TestExtractNextData:
    def test_extracts_valid_blob(self) -> None:
        html = _wrap_next_data({"hello": "world"})
        assert _extract_next_data(html) == {"hello": "world"}

    def test_missing_script_tag_raises(self) -> None:
        with pytest.raises(SpotifyError, match="__NEXT_DATA__"):
            _extract_next_data("<html><body>no script</body></html>")

    def test_invalid_json_raises(self) -> None:
        bad = (
            '<script id="__NEXT_DATA__" type="application/json">'
            "{not valid json"
            "</script>"
        )
        with pytest.raises(SpotifyError, match="not valid JSON"):
            _extract_next_data(bad)


# ============================================================
# _track_from_embed_item
# ============================================================


def _embed_item(
    *,
    track_id: str = "spot1234567890123456789",
    title: str = "Some Song",
    subtitle: str = "Artist A, Artist B",
    duration: int = 180_000,
    preview_url: str | None = "https://p.scdn.co/mp3-preview/abc",
) -> dict[str, Any]:
    """Construct a fake trackList entry shaped like the Spotify embed page's."""
    return {
        "uri": f"spotify:track:{track_id}",
        "uid": "x",
        "title": title,
        "subtitle": subtitle,
        "duration": duration,
        "audioPreview": {"url": preview_url} if preview_url is not None else None,
    }


class TestTrackFromEmbedItem:
    def test_happy_path(self) -> None:
        item = _embed_item(track_id="abc", title="Song", subtitle="Solo")
        t = _track_from_embed_item(item)
        assert t.spotify_id == "abc"
        assert t.title == "Song"
        assert t.artists == ("Solo",)
        assert t.duration_ms == 180_000
        assert t.preview_url == "https://p.scdn.co/mp3-preview/abc"
        assert t.isrc is None

    def test_multiple_artists_split_on_comma(self) -> None:
        item = _embed_item(subtitle="Artist A, Artist B, Artist C")
        t = _track_from_embed_item(item)
        assert t.artists == ("Artist A", "Artist B", "Artist C")

    def test_nbsp_after_comma_handled(self) -> None:
        """Spotify sometimes uses NBSP (U+00A0) after the comma in artist
        joins; the parser must split on it just like an ASCII space.
        """
        item = _embed_item(subtitle="Justin Bieber, Nicki Minaj")
        t = _track_from_embed_item(item)
        assert t.artists == ("Justin Bieber", "Nicki Minaj")

    def test_no_audio_preview_yields_none_url(self) -> None:
        item = _embed_item(preview_url=None)
        t = _track_from_embed_item(item)
        assert t.preview_url is None

    def test_audio_preview_present_but_url_missing(self) -> None:
        item = {
            "uri": "spotify:track:abc",
            "title": "T",
            "subtitle": "A",
            "duration": 100,
            "audioPreview": {},  # no 'url' key
        }
        t = _track_from_embed_item(item)
        assert t.preview_url is None


# ============================================================
# fetch_playlist_tracks (integration via httpx.MockTransport)
# ============================================================


def _make_embed_html(tracks: list[dict[str, Any]]) -> str:
    """Build a full embed-page HTML string with the supplied tracks."""
    payload = {
        "props": {
            "pageProps": {
                "state": {
                    "data": {
                        "entity": {
                            "name": "Test Playlist",
                            "uri": f"spotify:playlist:{VALID_ID}",
                            "trackList": tracks,
                        }
                    }
                }
            }
        }
    }
    return _wrap_next_data(payload)


class TestFetchPlaylistTracks:
    def test_happy_path(self) -> None:
        items = [
            _embed_item(track_id="t1", title="One", subtitle="A"),
            _embed_item(track_id="t2", title="Two", subtitle="B, C"),
        ]
        html = _make_embed_html(items)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "open.spotify.com"
            assert "/embed/playlist/" in str(request.url.path)
            return httpx.Response(200, text=html)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        tracks = fetch_playlist_tracks(VALID_ID, client=client)

        assert len(tracks) == 2
        assert tracks[0] == Track(
            spotify_id="t1",
            isrc=None,
            title="One",
            artists=("A",),
            duration_ms=180_000,
            preview_url="https://p.scdn.co/mp3-preview/abc",
        )
        assert tracks[1].artists == ("B", "C")

    def test_accepts_full_playlist_url(self) -> None:
        items = [_embed_item(track_id="t1", title="One", subtitle="A")]
        html = _make_embed_html(items)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=html)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        url = f"https://open.spotify.com/playlist/{VALID_ID}?si=abc"
        tracks = fetch_playlist_tracks(url, client=client)
        assert len(tracks) == 1

    def test_4xx_response_raises(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(SpotifyError, match="HTTP 404"):
            fetch_playlist_tracks(VALID_ID, client=client)

    def test_missing_tracklist_path_raises(self) -> None:
        broken_payload = {"props": {"pageProps": {"state": {"data": {}}}}}
        html = _wrap_next_data(broken_payload)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=html)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(SpotifyError, match="trackList"):
            fetch_playlist_tracks(VALID_ID, client=client)

    def test_missing_next_data_raises(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>nothing here</body></html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(SpotifyError, match="__NEXT_DATA__"):
            fetch_playlist_tracks(VALID_ID, client=client)

    def test_url_pattern_correct(self) -> None:
        """Verify the request goes to the embed (not API) endpoint."""
        observed = {"url": ""}

        def handler(request: httpx.Request) -> httpx.Response:
            observed["url"] = str(request.url)
            return httpx.Response(200, text=_make_embed_html([]))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetch_playlist_tracks(VALID_ID, client=client)
        assert observed["url"] == EMBED_URL_TEMPLATE.format(playlist_id=VALID_ID)
