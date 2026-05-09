"""Tests for stemguessr.manifest module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemguessr.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ManifestError,
    TrackBuildEntry,
    build_manifest,
)
from stemguessr.spotify import Track


def _make_track(spotify_id: str = "abc123", isrc: str | None = "USABC1234567") -> Track:
    return Track(
        spotify_id=spotify_id,
        isrc=isrc,
        title="Test Song",
        artists=("Artist One", "Artist Two"),
        duration_ms=200_000,
    )


def _make_stem_files(stem_dir: Path, stems: tuple[str, ...]) -> dict[str, Path]:
    """Create empty placeholder WAV files for each stem under stem_dir."""
    stem_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for stem in stems:
        path = stem_dir / f"{stem}.wav"
        path.write_bytes(b"\x00" * 44)
        paths[stem] = path
    return paths


class TestBuildManifestBasic:
    def test_writes_manifest_with_all_fields(self, tmp_path: Path) -> None:
        stems = ("drums", "bass", "vocals", "other")
        stem_paths = _make_stem_files(tmp_path / "stems" / "USABC1234567", stems)
        entry = TrackBuildEntry(track=_make_track(), stem_paths=stem_paths)

        manifest_path = build_manifest(
            playlist_id="37i9dQZF1DXcBWIGoYBM5M",
            playlist_url=("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
            model="htdemucs",
            stems=stems,
            entries=[entry],
            output_dir=tmp_path,
        )

        assert manifest_path == tmp_path / MANIFEST_FILENAME
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["version"] == MANIFEST_VERSION
        assert data["model"] == "htdemucs"
        assert data["stems"] == list(stems)
        assert data["source_playlist"]["spotify_id"] == "37i9dQZF1DXcBWIGoYBM5M"
        assert data["source_playlist"]["url"].startswith("https://open.spotify.com/")

        # Generated-at should be ISO 8601 UTC.
        assert data["generated_at"].endswith("+00:00")

        assert len(data["tracks"]) == 1
        track = data["tracks"][0]
        assert track["id"] == "USABC1234567"
        assert track["spotify_id"] == "abc123"
        assert track["isrc"] == "USABC1234567"
        assert track["title"] == "Test Song"
        assert track["artists"] == ["Artist One", "Artist Two"]
        assert track["duration_ms"] == 200_000

    def test_stem_paths_are_posix_relative_urls(self, tmp_path: Path) -> None:
        """Stem paths in the manifest must be POSIX (forward slashes) and
        relative to output_dir; the frontend uses them as static asset URLs.
        """
        stems = ("drums", "bass", "vocals", "other")
        stem_paths = _make_stem_files(tmp_path / "stems" / "USABC1234567", stems)
        entry = TrackBuildEntry(track=_make_track(), stem_paths=stem_paths)

        manifest_path = build_manifest(
            playlist_id="p",
            playlist_url="u",
            model="htdemucs",
            stems=stems,
            entries=[entry],
            output_dir=tmp_path,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for stem in stems:
            assert data["tracks"][0]["stems"][stem] == (
                f"stems/USABC1234567/{stem}.wav"
            )
            # No backslashes regardless of host OS
            assert "\\" not in data["tracks"][0]["stems"][stem]


class TestIdResolution:
    """The track ``id`` field is the ISRC when available, else the Spotify ID.

    Rationale: ISRC is industry-standard and stable; Spotify IDs are
    Spotify-specific and survive only inside their own catalogue.
    """

    def test_uses_isrc_when_present(self, tmp_path: Path) -> None:
        stems = ("drums",)
        stem_paths = _make_stem_files(tmp_path / "stems" / "ID", stems)
        entry = TrackBuildEntry(
            track=_make_track(spotify_id="spot_id", isrc="USABC1234567"),
            stem_paths=stem_paths,
        )
        manifest_path = build_manifest(
            playlist_id="p",
            playlist_url="u",
            model="htdemucs",
            stems=stems,
            entries=[entry],
            output_dir=tmp_path,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["tracks"][0]["id"] == "USABC1234567"

    def test_falls_back_to_spotify_id_when_isrc_is_none(self, tmp_path: Path) -> None:
        stems = ("drums",)
        stem_paths = _make_stem_files(tmp_path / "stems" / "ID", stems)
        entry = TrackBuildEntry(
            track=_make_track(spotify_id="spot_id_42", isrc=None),
            stem_paths=stem_paths,
        )
        manifest_path = build_manifest(
            playlist_id="p",
            playlist_url="u",
            model="htdemucs",
            stems=stems,
            entries=[entry],
            output_dir=tmp_path,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["tracks"][0]["id"] == "spot_id_42"


class TestErrors:
    def test_missing_stem_raises(self, tmp_path: Path) -> None:
        # Only 1 of 4 expected stems present
        stems = ("drums", "bass", "vocals", "other")
        partial = _make_stem_files(tmp_path / "stems" / "ID", ("drums",))
        entry = TrackBuildEntry(track=_make_track(), stem_paths=partial)

        with pytest.raises(ManifestError, match="missing stems"):
            build_manifest(
                playlist_id="p",
                playlist_url="u",
                model="htdemucs",
                stems=stems,
                entries=[entry],
                output_dir=tmp_path,
            )

    def test_path_outside_output_dir_raises(self, tmp_path: Path) -> None:
        elsewhere = tmp_path.parent / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        stem = elsewhere / "drums.wav"
        stem.write_bytes(b"\x00" * 44)
        entry = TrackBuildEntry(
            track=_make_track(),
            stem_paths={"drums": stem},
        )
        with pytest.raises(ManifestError, match="not under output_dir"):
            build_manifest(
                playlist_id="p",
                playlist_url="u",
                model="htdemucs",
                stems=("drums",),
                entries=[entry],
                output_dir=tmp_path,
            )


class TestOrderingAndMultiple:
    def test_track_order_preserved(self, tmp_path: Path) -> None:
        stems = ("drums",)
        entries: list[TrackBuildEntry] = []
        ids = ["USABC1234567", "USDEF7654321", "USGHI1111111"]
        for tid in ids:
            paths = _make_stem_files(tmp_path / "stems" / tid, stems)
            entries.append(
                TrackBuildEntry(
                    track=_make_track(spotify_id=tid, isrc=tid),
                    stem_paths=paths,
                )
            )

        manifest_path = build_manifest(
            playlist_id="p",
            playlist_url="u",
            model="htdemucs",
            stems=stems,
            entries=entries,
            output_dir=tmp_path,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert [t["id"] for t in data["tracks"]] == ids

    def test_empty_playlist_produces_empty_tracks_list(self, tmp_path: Path) -> None:
        manifest_path = build_manifest(
            playlist_id="p",
            playlist_url="u",
            model="htdemucs",
            stems=("drums", "bass", "vocals", "other"),
            entries=[],
            output_dir=tmp_path,
        )
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["tracks"] == []
        assert data["version"] == MANIFEST_VERSION
