"""Manifest builder.

Assembles ``manifest.json`` — the contract between the ingest pipeline and
the static frontend. Each entry pairs a Spotify :class:`~stemguessr.spotify.Track`
with the on-disk stem WAVs produced by the separation stage; the builder
serialises stem paths as POSIX-relative URLs so the frontend can resolve them
as static asset paths.

Schema version: 1.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stemguessr.spotify import Track

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"


class ManifestError(RuntimeError):
    """Raised when manifest construction fails (missing stems, paths
    not under ``output_dir``, etc.)."""


@dataclass(frozen=True, slots=True)
class TrackBuildEntry:
    """Inputs to the manifest builder for a single track.

    Attributes:
        track: Spotify :class:`Track` carrying title, artists, ISRC, etc.
        stem_paths: Map of stem name (``"drums"``, …) to the on-disk path
            of the corresponding WAV file. Paths must be located under the
            ``output_dir`` passed to :func:`build_manifest`.
    """

    track: Track
    stem_paths: dict[str, Path]


def build_manifest(
    *,
    playlist_id: str,
    playlist_url: str,
    model: str,
    stems: tuple[str, ...],
    entries: list[TrackBuildEntry],
    output_dir: Path,
) -> Path:
    """Build ``manifest.json`` under ``output_dir`` and return its path.

    Each entry must contain a path for every name in ``stems``; otherwise
    :class:`ManifestError` is raised. Stem paths must be under ``output_dir``
    so they can be serialised as POSIX-relative URLs for the frontend.

    Track order in the resulting manifest matches the order of ``entries``.

    Args:
        playlist_id: 22-char Spotify playlist ID for traceability.
        playlist_url: Original URL/URI the user supplied.
        model: ``"htdemucs"`` or ``"htdemucs_6s"``; recorded in manifest.
        stems: Ordered stem names for ``model``; the frontend renders rounds
            in this order.
        entries: Per-track inputs; one row in ``manifest.tracks`` per entry.
        output_dir: Directory to write the manifest into; created if missing.
            All ``stem_paths`` must be located under this directory.

    Returns:
        Path to the written ``manifest.json``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source_playlist": {
            "spotify_id": playlist_id,
            "url": playlist_url,
        },
        "model": model,
        "stems": list(stems),
        "tracks": [_serialize_entry(e, stems, output_dir) for e in entries],
    }
    manifest_path = output_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def _serialize_entry(
    entry: TrackBuildEntry,
    stems: tuple[str, ...],
    output_dir: Path,
) -> dict[str, Any]:
    """Render one TrackBuildEntry into its manifest-row dict shape."""
    missing = [s for s in stems if s not in entry.stem_paths]
    if missing:
        raise ManifestError(
            f"Track {entry.track.spotify_id!r} missing stems: {missing}"
        )

    stem_urls: dict[str, str] = {}
    for stem in stems:
        path = entry.stem_paths[stem]
        try:
            relative = path.resolve().relative_to(output_dir.resolve())
        except ValueError as e:
            raise ManifestError(
                f"Stem path {path} is not under output_dir {output_dir}"
            ) from e
        stem_urls[stem] = relative.as_posix()

    return {
        "id": entry.track.isrc or entry.track.spotify_id,
        "spotify_id": entry.track.spotify_id,
        "isrc": entry.track.isrc,
        "title": entry.track.title,
        "artists": list(entry.track.artists),
        "duration_ms": entry.track.duration_ms,
        "stems": stem_urls,
    }
