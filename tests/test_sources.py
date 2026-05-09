"""Tests for stemguessr.sources module.

All tests run offline. HTTP is faked via ``httpx.MockTransport``; no real
network access is performed. ``time.sleep`` is monkeypatched at module scope
so retry-backoff paths run instantly.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from stemguessr.sources import (
    PreviewMatch,
    SourceError,
    _request_with_retry,
    get_preview,
    lookup_deezer,
    lookup_itunes,
)

# Use a syntactically valid ISRC throughout. (Format: 2 country + 3 owner +
# 2 year + 5 designation = 12 chars; we treat it as opaque.)
ISRC = "USABC1234567"


@pytest.fixture(autouse=True)
def _no_real_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make all retry sleeps instant. Without this, retry-error tests would
    add ~7 seconds each from the 1+2+4-second backoff schedule.
    """
    monkeypatch.setattr("stemguessr.sources.time.sleep", lambda _: None)


def _make_client(handler) -> httpx.Client:
    """Construct an httpx.Client whose every request is dispatched to ``handler``."""
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- iTunes lookup ---


class TestLookupItunes:
    def test_hit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "itunes.apple.com" in str(request.url)
            assert request.url.params.get("isrc") == ISRC
            return httpx.Response(
                200,
                json={
                    "resultCount": 1,
                    "results": [
                        {"previewUrl": "https://audio.itunes.example/p.m4a"},
                    ],
                },
            )

        client = _make_client(handler)
        match = lookup_itunes(client, ISRC)
        assert match == PreviewMatch(
            isrc=ISRC,
            source="itunes",
            url="https://audio.itunes.example/p.m4a",
            extension="m4a",
        )

    def test_miss_empty_results(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"resultCount": 0, "results": []})

        client = _make_client(handler)
        assert lookup_itunes(client, ISRC) is None

    def test_miss_no_preview_url(self) -> None:
        """Result exists but has no previewUrl field — treat as a miss."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"resultCount": 1, "results": [{"trackId": 1}]},
            )

        client = _make_client(handler)
        assert lookup_itunes(client, ISRC) is None

    def test_non_json_raises_source_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>")

        client = _make_client(handler)
        with pytest.raises(SourceError, match="non-JSON"):
            lookup_itunes(client, ISRC)


# --- Deezer lookup ---


class TestLookupDeezer:
    def test_hit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "api.deezer.com" in str(request.url)
            assert f"isrc:{ISRC}" in str(request.url)
            return httpx.Response(
                200,
                json={"id": 12345, "preview": "https://cdns.deezer.example/p.mp3"},
            )

        client = _make_client(handler)
        match = lookup_deezer(client, ISRC)
        assert match == PreviewMatch(
            isrc=ISRC,
            source="deezer",
            url="https://cdns.deezer.example/p.mp3",
            extension="mp3",
        )

    def test_miss_via_error_object(self) -> None:
        """Deezer's documented miss path: 200 with {"error": ...}."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"error": {"type": "DataException", "message": "no data"}},
            )

        client = _make_client(handler)
        assert lookup_deezer(client, ISRC) is None

    def test_miss_via_4xx(self) -> None:
        """Some Deezer endpoints return 4xx for unknown ISRCs; treat as miss."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"code": 800}})

        client = _make_client(handler)
        assert lookup_deezer(client, ISRC) is None

    def test_5xx_propagates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"upstream down")

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            lookup_deezer(client, ISRC)


# --- Retry helper ---


class TestRequestWithRetry:
    def test_429_then_success(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"ok": True})

        client = _make_client(handler)
        response = _request_with_retry(client, "https://x.example/")
        assert response.status_code == 200
        assert calls["n"] == 2

    def test_network_error_recovers(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("simulated network failure")
            return httpx.Response(200)

        client = _make_client(handler)
        response = _request_with_retry(client, "https://x.example/")
        assert response.status_code == 200
        assert calls["n"] == 3

    def test_exhausts_retries_then_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("always fails")

        client = _make_client(handler)
        with pytest.raises(httpx.ConnectError):
            _request_with_retry(client, "https://x.example/", max_retries=2)


# --- get_preview integration ---


class TestGetPreview:
    AUDIO = b"\x00\x01\x02fake-audio-bytes"

    def test_cache_hit_skips_network(self, tmp_path: Path) -> None:
        previews = tmp_path / "previews"
        previews.mkdir()
        cached = previews / f"{ISRC}.m4a"
        cached.write_bytes(b"cached audio")

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                f"cache hit should not have made a network call: {request.url}"
            )

        client = _make_client(handler)
        result = get_preview(ISRC, tmp_path, client=client)
        assert result == cached

    def test_full_flow_itunes_first_succeeds(self, tmp_path: Path) -> None:
        audio_url = "https://audio.itunes.example/p.m4a"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "itunes.apple.com" in url:
                return httpx.Response(
                    200,
                    json={"results": [{"previewUrl": audio_url}]},
                )
            if url == audio_url:
                return httpx.Response(200, content=self.AUDIO)
            raise AssertionError(f"unexpected request: {url}")

        client = _make_client(handler)
        result = get_preview(ISRC, tmp_path, client=client)
        assert result is not None
        assert result == tmp_path / "previews" / f"{ISRC}.m4a"
        assert result.read_bytes() == self.AUDIO

    def test_falls_back_to_deezer_on_itunes_miss(self, tmp_path: Path) -> None:
        audio_url = "https://cdns.deezer.example/p.mp3"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "itunes.apple.com" in url:
                return httpx.Response(200, json={"results": []})
            if "api.deezer.com" in url:
                return httpx.Response(200, json={"preview": audio_url, "id": 1})
            if url == audio_url:
                return httpx.Response(200, content=self.AUDIO)
            raise AssertionError(f"unexpected request: {url}")

        client = _make_client(handler)
        result = get_preview(ISRC, tmp_path, client=client)
        assert result is not None
        assert result.suffix == ".mp3"
        assert result.read_bytes() == self.AUDIO

    def test_returns_none_when_both_sources_miss(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "itunes.apple.com" in url:
                return httpx.Response(200, json={"results": []})
            if "api.deezer.com" in url:
                return httpx.Response(200, json={"error": {"message": "no data"}})
            raise AssertionError(f"unexpected request: {url}")

        client = _make_client(handler)
        assert get_preview(ISRC, tmp_path, client=client) is None
        # Cache directory should not have been populated.
        assert not (tmp_path / "previews" / f"{ISRC}.m4a").exists()
        assert not (tmp_path / "previews" / f"{ISRC}.mp3").exists()

    def test_atomic_write_no_partial_file(self, tmp_path: Path) -> None:
        """If the audio download fails midway (4xx/5xx), no .m4a/.mp3 file
        should be left in the cache; only a .tmp may remain (and we don't
        guarantee even that).
        """
        audio_url = "https://audio.itunes.example/p.m4a"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "itunes.apple.com" in url:
                return httpx.Response(
                    200, json={"results": [{"previewUrl": audio_url}]}
                )
            if url == audio_url:
                return httpx.Response(503, content=b"upstream gone")
            raise AssertionError(f"unexpected request: {url}")

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            get_preview(ISRC, tmp_path, client=client)
        final = tmp_path / "previews" / f"{ISRC}.m4a"
        assert not final.exists(), "partial file leaked into cache"
