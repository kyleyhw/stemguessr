"""Tests for stemguessr.cli — the orchestration layer.

Each pipeline stage (Spotify, preview download, separation, manifest) is
mocked at the ``stemguessr.cli`` import boundary, so these tests exercise
the orchestration logic alone — error handling, skip-on-miss, force-refresh,
exit codes, --version, --limit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from stemguessr.cli import __version__, app
from stemguessr.manifest import MANIFEST_FILENAME
from stemguessr.separate import MODEL_STEMS
from stemguessr.spotify import Track

runner = CliRunner()

VALID_PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
VALID_PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"


_DEFAULT_PREVIEW = "https://p.scdn.co/mp3-preview/default"


def _make_track(
    spotify_id: str,
    preview_url: str | None = _DEFAULT_PREVIEW,
    title: str = "Song",
    artists: tuple[str, ...] = ("Artist",),
) -> Track:
    return Track(
        spotify_id=spotify_id,
        isrc=None,
        title=title,
        artists=artists,
        duration_ms=200_000,
        preview_url=preview_url,
    )


@dataclass
class StubState:
    """Mutable container shared between the fixture's fake stages and tests.

    Tests pre-set ``tracks`` to control behaviour and read
    ``download_calls`` / ``separate_calls`` to assert on what the CLI did.
    """

    tracks: list[Track] = field(default_factory=list)
    download_calls: list[dict[str, Any]] = field(default_factory=list)
    separate_calls: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> StubState:
    """Replace every pipeline stage with a controllable stub.

    Returns a :class:`StubState` whose mutable fields tests can read and
    pre-mutate.
    """
    state = StubState(
        tracks=[_make_track(f"tid{i}") for i in range(2)],
    )

    def fake_fetch_playlist_tracks(playlist_url: str) -> list[Track]:
        # Sanity: CLI passes the original URL straight through.
        assert "spotify.com" in playlist_url or playlist_url.startswith("spotify:")
        return state.tracks

    def fake_download_preview(
        url: str,
        cache_key: str,
        cache_dir: Path,
        **_kwargs: Any,
    ) -> Path:
        state.download_calls.append(
            {"url": url, "cache_key": cache_key, "cache_dir": cache_dir}
        )
        previews = cache_dir / "previews"
        previews.mkdir(parents=True, exist_ok=True)
        path = previews / f"{cache_key}.mp3"
        path.write_bytes(b"\x00" * 16)
        return path

    def fake_separate(
        input_path: Path, output_dir: Path, *, model: str
    ) -> dict[str, Path]:
        state.separate_calls.append(
            {"input": input_path, "output": output_dir, "model": model}
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for stem in MODEL_STEMS[model]:
            p = output_dir / f"{stem}.wav"
            p.write_bytes(b"\x00" * 44)
            paths[stem] = p
        return paths

    def fake_fetch_track_cover_url(spotify_id: str) -> str | None:
        return f"https://example.cdn/cover/{spotify_id}.jpg"

    monkeypatch.setattr(
        "stemguessr.cli.fetch_playlist_tracks", fake_fetch_playlist_tracks
    )
    monkeypatch.setattr(
        "stemguessr.cli.fetch_track_cover_url", fake_fetch_track_cover_url
    )
    monkeypatch.setattr("stemguessr.cli.download_preview", fake_download_preview)
    monkeypatch.setattr("stemguessr.cli.separate", fake_separate)
    return state


class TestVersion:
    def test_version_flag_prints_version_and_exits(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        # Compare against the package's own version rather than a pinned
        # string, so version bumps do not break the test.
        assert f"stemguessr {__version__}" in result.stdout


class TestArgumentValidation:
    def test_invalid_stems_count_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path), "--stems", "5"],
        )
        assert result.exit_code == 1
        assert "must be 4 or 6" in result.stderr

    def test_invalid_playlist_url_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["ingest", "not a url at all", "--out", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "Not a Spotify URL" in result.stderr or "Invalid" in result.stderr


class TestHappyPath:
    def test_ingest_writes_manifest(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0, result.stdout + result.stderr

        manifest = tmp_path / MANIFEST_FILENAME
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["model"] == "htdemucs"
        assert data["source_playlist"]["spotify_id"] == VALID_PLAYLIST_ID
        assert len(data["tracks"]) == 2

    def test_separate_called_per_track_with_correct_model(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        runner.invoke(
            app,
            [
                "ingest",
                VALID_PLAYLIST_URL,
                "--out",
                str(tmp_path),
                "--stems",
                "6",
            ],
        )
        assert len(stub_pipeline.separate_calls) == 2
        for call in stub_pipeline.separate_calls:
            assert call["model"] == "htdemucs_6s"

    def test_download_called_with_track_preview_url(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        """The CLI must pass each track's preview_url straight through to
        download_preview, keyed by the track's Spotify ID. Processing order
        is shuffled, so compare as sets rather than positionally.
        """
        runner.invoke(app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)])
        assert len(stub_pipeline.download_calls) == 2
        expected = {(t.preview_url, t.spotify_id) for t in stub_pipeline.tracks}
        got = {(c["url"], c["cache_key"]) for c in stub_pipeline.download_calls}
        assert got == expected


class TestSkipping:
    def test_track_without_preview_url_is_skipped(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        stub_pipeline.tracks = [
            _make_track("a"),
            _make_track("b", preview_url=None),
        ]
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "no preview from Spotify" in result.stderr

        manifest = json.loads(
            (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert len(manifest["tracks"]) == 1
        assert manifest["tracks"][0]["spotify_id"] == "a"


class TestShuffledOrder:
    def test_processing_order_follows_shuffle(
        self,
        stub_pipeline: StubState,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The pipeline must process tracks in the order produced by
        random.shuffle, not playlist order — otherwise the first separated
        (and hence first playable) track is always the playlist's first.
        Replacing shuffle with a deterministic in-place reversal makes the
        expected order exact; five distinct IDs are used so a reversal
        cannot be mistaken for identity (as it could with 0 or 1 tracks).
        """
        stub_pipeline.tracks = [_make_track(f"id{i}") for i in range(5)]
        monkeypatch.setattr("stemguessr.cli.random.shuffle", lambda seq: seq.reverse())
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0
        got = [c["cache_key"] for c in stub_pipeline.download_calls]
        assert got == [f"id{i}" for i in reversed(range(5))]

    def test_playlist_track_list_not_mutated(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        """The shuffle must operate on a copy: the list returned by
        fetch_playlist_tracks (aliased by the stub) must keep its original
        playlist order after the run.
        """
        stub_pipeline.tracks = [_make_track(f"id{i}") for i in range(5)]
        original = list(stub_pipeline.tracks)
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert stub_pipeline.tracks == original


class TestLimit:
    def test_limit_caps_track_count(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        stub_pipeline.tracks = [_make_track(f"id{i}") for i in range(5)]
        result = runner.invoke(
            app,
            [
                "ingest",
                VALID_PLAYLIST_URL,
                "--out",
                str(tmp_path),
                "--limit",
                "2",
            ],
        )
        assert result.exit_code == 0
        assert len(stub_pipeline.separate_calls) == 2

        manifest = json.loads(
            (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert len(manifest["tracks"]) == 2


class TestForceRefresh:
    def test_force_refresh_clears_existing_caches(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        track = stub_pipeline.tracks[0]
        track_id = track.spotify_id
        (tmp_path / "previews").mkdir()
        stale_preview = tmp_path / "previews" / f"{track_id}.mp3"
        stale_preview.write_bytes(b"STALE")
        stale_stem_dir = tmp_path / "stems" / track_id
        stale_stem_dir.mkdir(parents=True)
        (stale_stem_dir / "drums.wav").write_bytes(b"STALE")

        result = runner.invoke(
            app,
            [
                "ingest",
                VALID_PLAYLIST_URL,
                "--out",
                str(tmp_path),
                "--force-refresh",
            ],
        )
        assert result.exit_code == 0

        # Both files were re-created with non-stale content by the stubs.
        assert stale_preview.exists()
        assert stale_preview.read_bytes() != b"STALE"
        assert (stale_stem_dir / "drums.wav").read_bytes() != b"STALE"
