"""Tests for stemguessr.cli — the orchestration layer.

Each pipeline stage (Spotify, sources, separate, manifest) is mocked at the
``stemguessr.cli`` import boundary, so these tests exercise the orchestration
logic alone — error handling, skip-on-miss, force-refresh, exit codes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from stemguessr.cli import app
from stemguessr.manifest import MANIFEST_FILENAME
from stemguessr.separate import MODEL_STEMS
from stemguessr.spotify import Track

runner = CliRunner()

VALID_PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
VALID_PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"


def _make_track(
    spotify_id: str,
    isrc: str | None = None,
    title: str = "Song",
    artists: tuple[str, ...] = ("Artist",),
) -> Track:
    if isrc is None:
        isrc = f"USXX{spotify_id[:8]}"
    return Track(
        spotify_id=spotify_id,
        isrc=isrc,
        title=title,
        artists=artists,
        duration_ms=200_000,
    )


@dataclass
class StubState:
    """Mutable container shared between the fixture's fake stages and tests.

    Tests pre-set ``tracks`` / ``preview_returns`` to control behaviour and
    then read ``separate_calls`` / ``preview_calls`` to assert on what the
    CLI did.
    """

    tracks: list[Track] = field(default_factory=list)
    preview_returns: dict[str, Path | None] = field(default_factory=dict)
    separate_calls: list[dict[str, Any]] = field(default_factory=list)
    preview_calls: list[str] = field(default_factory=list)


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> StubState:
    """Replace every pipeline stage with a controllable stub.

    Returns a :class:`StubState` whose mutable fields tests can read and
    pre-mutate.
    """
    state = StubState(
        tracks=[_make_track(f"tid{i}") for i in range(2)],
    )

    def fake_get_client() -> object:
        return object()

    def fake_fetch_playlist_tracks(_client: object, playlist_id: str) -> list[Track]:
        assert playlist_id == VALID_PLAYLIST_ID
        return state.tracks

    def fake_get_preview(isrc: str, cache_dir: Path) -> Path | None:
        state.preview_calls.append(isrc)
        if isrc in state.preview_returns:
            return state.preview_returns[isrc]
        previews = cache_dir / "previews"
        previews.mkdir(parents=True, exist_ok=True)
        path = previews / f"{isrc}.m4a"
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

    monkeypatch.setattr("stemguessr.cli.get_client", fake_get_client)
    monkeypatch.setattr(
        "stemguessr.cli.fetch_playlist_tracks", fake_fetch_playlist_tracks
    )
    monkeypatch.setattr("stemguessr.cli.get_preview", fake_get_preview)
    monkeypatch.setattr("stemguessr.cli.separate", fake_separate)
    return state


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


class TestSkipping:
    def test_track_without_isrc_is_skipped(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        stub_pipeline.tracks = [
            _make_track("a"),
            Track(
                spotify_id="b",
                isrc=None,
                title="Local",
                artists=("Owner",),
                duration_ms=0,
            ),
        ]
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "no ISRC" in result.stderr

        manifest = json.loads(
            (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert len(manifest["tracks"]) == 1
        assert manifest["tracks"][0]["spotify_id"] == "a"

    def test_track_with_no_preview_is_skipped(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        stub_pipeline.preview_returns = {"USXXtid1": None}
        result = runner.invoke(
            app, ["ingest", VALID_PLAYLIST_URL, "--out", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "no preview source has" in result.stderr

        manifest = json.loads(
            (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert len(manifest["tracks"]) == 1


class TestForceRefresh:
    def test_force_refresh_clears_existing_caches(
        self, stub_pipeline: StubState, tmp_path: Path
    ) -> None:
        track = stub_pipeline.tracks[0]
        assert track.isrc is not None  # narrowed for type checker
        isrc = track.isrc
        (tmp_path / "previews").mkdir()
        stale_preview = tmp_path / "previews" / f"{isrc}.m4a"
        stale_preview.write_bytes(b"STALE")
        stale_stem_dir = tmp_path / "stems" / isrc
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

        # Both files were re-created with non-stale content.
        assert stale_preview.exists()
        assert stale_preview.read_bytes() != b"STALE"
        assert (stale_stem_dir / "drums.wav").read_bytes() != b"STALE"
