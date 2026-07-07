"""Schema validation for the frontend fixture manifest.

The fixture at ``tests/fixtures/manifest.json`` is hand-edited; this test
guards against drift between it and the schema produced by
``stemguessr.manifest``. The frontend (Phase 7) trusts that any manifest with
``version: 1`` matches the documented shape, so a malformed fixture would
silently break offline frontend development without this check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "manifest.json"


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_exists() -> None:
    assert FIXTURE_PATH.exists(), f"missing fixture: {FIXTURE_PATH}"


def test_top_level_fields_present(fixture_data: dict) -> None:
    for required in (
        "version",
        "generated_at",
        "complete",
        "source_playlist",
        "model",
        "stems",
        "tracks",
    ):
        assert required in fixture_data, f"missing top-level field: {required!r}"


def test_complete_is_bool(fixture_data: dict) -> None:
    assert isinstance(fixture_data["complete"], bool)


def test_version_is_one(fixture_data: dict) -> None:
    assert fixture_data["version"] == 1


def test_stems_is_nonempty_string_list(fixture_data: dict) -> None:
    stems = fixture_data["stems"]
    assert isinstance(stems, list)
    assert len(stems) > 0
    assert all(isinstance(s, str) for s in stems)


def test_each_track_has_complete_stem_map(fixture_data: dict) -> None:
    """Every track must contain a path for every name in the top-level
    ``stems`` array; otherwise the frontend will throw on stem lookup.
    """
    expected_stems = set(fixture_data["stems"])
    for track in fixture_data["tracks"]:
        track_stems = set(track["stems"].keys())
        missing = expected_stems - track_stems
        assert not missing, f"track {track.get('id')!r} missing stems: {missing}"


def test_track_required_fields(fixture_data: dict) -> None:
    for track in fixture_data["tracks"]:
        for required in (
            "id",
            "spotify_id",
            "title",
            "artists",
            "duration_ms",
            "stems",
        ):
            assert required in track, (
                f"track {track.get('id')!r} missing field: {required!r}"
            )


def test_stem_paths_are_posix_relative(fixture_data: dict) -> None:
    """Stem paths must be POSIX (forward slashes), relative (no leading '/'
    or scheme) — the frontend resolves them as static asset URLs.
    """
    for track in fixture_data["tracks"]:
        for stem_name, path in track["stems"].items():
            assert isinstance(path, str), f"non-string stem path: {path}"
            assert "\\" not in path, f"backslash in stem path: {path}"
            assert not path.startswith("/"), f"leading-slash in stem path: {path}"
            assert "://" not in path, f"absolute URL in stem path: {path}"
