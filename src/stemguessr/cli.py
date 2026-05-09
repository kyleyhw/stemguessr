"""Command-line interface for StemGuessr.

Composes the Spotify ingest, preview-source, separation, and manifest modules
into a single ``stemguessr ingest <playlist_url>`` command. The command is
intentionally one big procedural function: each stage is short, the data flow
is linear, and per-track failures are reported and skipped rather than
aborting the whole run.

Public entry points:

* :data:`app` — the :class:`typer.Typer` application; tests invoke via
  ``typer.testing.CliRunner``.
* :func:`main` — module-level entry referenced by ``[project.scripts]``.
"""

from __future__ import annotations

import shutil
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer

try:
    __version__ = _pkg_version("stemguessr")
except PackageNotFoundError:  # editable install before metadata regeneration
    __version__ = "0.0.0+unknown"

from stemguessr.manifest import (
    TrackBuildEntry,
    build_manifest,
)
from stemguessr.separate import MODEL_STEMS, separate
from stemguessr.sources import get_preview
from stemguessr.spotify import (
    SpotifyError,
    Track,
    fetch_playlist_tracks,
    get_client,
    parse_playlist_id,
)

app = typer.Typer(
    name="stemguessr",
    help=(
        "Ingest a Spotify playlist into Demucs-separated stems for the StemGuessr game."
    ),
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print version and exit (used by ``--version`` flag)."""
    if value:
        typer.echo(f"stemguessr {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[  # noqa: ARG001 (callback consumes the value via Typer)
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """Root callback — exposes ``--version`` and forces typer into subcommand
    mode (single-command Typer apps otherwise auto-promote to root, breaking
    the documented ``stemguessr ingest <url>`` invocation).
    """


def _model_for_stems(n_stems: int) -> str:
    """Map the integer ``--stems`` flag to a Demucs model name.

    Raises:
        ValueError: ``n_stems`` is not 4 or 6.
    """
    if n_stems == 4:
        return "htdemucs"
    if n_stems == 6:
        return "htdemucs_6s"
    raise ValueError(f"--stems must be 4 or 6 (got {n_stems})")


def _clear_track_cache(track_isrc: str, cache_dir: Path) -> None:
    """Remove the cached preview and stem outputs for a single ISRC."""
    for ext in ("m4a", "mp3"):
        (cache_dir / "previews" / f"{track_isrc}.{ext}").unlink(missing_ok=True)
    stems_dir = cache_dir / "stems" / track_isrc
    if stems_dir.exists():
        shutil.rmtree(stems_dir)


def _process_track(
    track: Track,
    cache_dir: Path,
    model: str,
    force_refresh: bool,
) -> TrackBuildEntry | None:
    """Run the per-track pipeline: optional cache clear → preview → separation.

    Returns a :class:`TrackBuildEntry` on success, or ``None`` if the track
    must be skipped (no ISRC; no source has a preview). Side effects: writes
    files into ``cache_dir``.
    """
    if not track.isrc:
        typer.echo(
            f"  skip: no ISRC for {track.title!r} — {', '.join(track.artists)}",
            err=True,
        )
        return None

    if force_refresh:
        _clear_track_cache(track.isrc, cache_dir)

    preview_path = get_preview(track.isrc, cache_dir)
    if preview_path is None:
        typer.echo(
            f"  skip: no preview source has ISRC {track.isrc} ({track.title!r})",
            err=True,
        )
        return None

    stem_dir = cache_dir / "stems" / track.isrc
    stem_paths = separate(preview_path, stem_dir, model=model)
    return TrackBuildEntry(track=track, stem_paths=stem_paths)


@app.command()
def ingest(
    playlist_url: Annotated[
        str,
        typer.Argument(
            help=(
                "Spotify playlist URL or URI: open.spotify.com/playlist/<id>, "
                "intl-XX/playlist/<id>, or spotify:playlist:<id>."
            ),
        ),
    ],
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            "-o",
            help="Cache root directory (holds previews/, stems/, manifest.json).",
        ),
    ] = Path("./cache"),
    n_stems: Annotated[
        int,
        typer.Option(
            "--stems",
            help="Number of stems: 4 (htdemucs) or 6 (htdemucs_6s).",
        ),
    ] = 4,
    force_refresh: Annotated[
        bool,
        typer.Option(
            "--force-refresh",
            help=(
                "Discard cached previews and stems for every track before "
                "re-processing."
            ),
        ),
    ] = False,
) -> None:
    """Ingest a Spotify playlist into stems and build the game manifest."""
    try:
        model = _model_for_stems(n_stems)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    try:
        playlist_id = parse_playlist_id(playlist_url)
    except SpotifyError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"Fetching tracks for playlist {playlist_id}...")
    try:
        client = get_client()
    except SpotifyError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    tracks = fetch_playlist_tracks(client, playlist_id)
    typer.echo(f"  {len(tracks)} tracks found.")

    entries: list[TrackBuildEntry] = []
    for i, track in enumerate(tracks, start=1):
        typer.echo(f"[{i}/{len(tracks)}] {track.title!r} — {', '.join(track.artists)}")
        entry = _process_track(track, out, model, force_refresh)
        if entry is not None:
            entries.append(entry)

    typer.echo(
        f"\nBuilding manifest: {len(entries)}/{len(tracks)} tracks have stems..."
    )
    manifest_path = build_manifest(
        playlist_id=playlist_id,
        playlist_url=playlist_url,
        model=model,
        stems=MODEL_STEMS[model],
        entries=entries,
        output_dir=out,
    )
    typer.echo(f"Done. Manifest at {manifest_path}")


def main() -> None:
    """Entry point referenced by ``[project.scripts] stemguessr = "stemguessr:main"``."""
    app()


if __name__ == "__main__":
    main()
