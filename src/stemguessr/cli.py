"""Command-line interface for StemGuessr.

Composes the Spotify ingest, preview-download, separation, and manifest
modules into a single ``stemguessr ingest <playlist_url>`` command. The
command is intentionally one big procedural function: each stage is short,
the data flow is linear, and per-track failures are reported and skipped
rather than aborting the whole run.

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
from stemguessr.sources import download_preview
from stemguessr.spotify import (
    SpotifyError,
    Track,
    fetch_playlist_tracks,
    parse_playlist_id,
)

app = typer.Typer(
    name="stemguessr",
    help=(
        "Ingest a public Spotify playlist into Demucs-separated stems for "
        "the StemGuessr game. No authentication required."
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


def _clear_track_cache(track_id: str, cache_dir: Path) -> None:
    """Remove the cached preview and stem outputs for a single track ID."""
    for ext in ("m4a", "mp3"):
        (cache_dir / "previews" / f"{track_id}.{ext}").unlink(missing_ok=True)
    stems_dir = cache_dir / "stems" / track_id
    if stems_dir.exists():
        shutil.rmtree(stems_dir)


def _process_track(
    track: Track,
    cache_dir: Path,
    model: str,
    force_refresh: bool,
) -> TrackBuildEntry | None:
    """Run the per-track pipeline: optional cache clear → preview download →
    separation.

    Returns a :class:`TrackBuildEntry` on success, or ``None`` if the track
    must be skipped (no preview URL from Spotify). Side effects: writes
    files into ``cache_dir``.
    """
    if not track.preview_url:
        typer.echo(
            f"  skip: no preview from Spotify for {track.title!r} — "
            f"{', '.join(track.artists)}",
            err=True,
        )
        return None

    track_id = track.spotify_id
    if force_refresh:
        _clear_track_cache(track_id, cache_dir)

    preview_path = download_preview(track.preview_url, track_id, cache_dir)
    stem_dir = cache_dir / "stems" / track_id
    stem_paths = separate(preview_path, stem_dir, model=model)
    return TrackBuildEntry(track=track, stem_paths=stem_paths)


@app.command()
def ingest(
    playlist_url: Annotated[
        str,
        typer.Argument(
            help=(
                "Public Spotify playlist URL or URI: open.spotify.com/playlist/<id>, "
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
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help=(
                "Process only the first N tracks of the playlist "
                "(useful for quick smoke tests)."
            ),
        ),
    ] = None,
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
        tracks = fetch_playlist_tracks(playlist_url)
    except SpotifyError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e

    if limit is not None:
        tracks = tracks[:limit]
        typer.echo(f"  {len(tracks)} tracks (limited from playlist by --limit).")
    else:
        typer.echo(f"  {len(tracks)} tracks found.")

    expected = len(tracks)
    entries: list[TrackBuildEntry] = []

    def _write_manifest(*, complete: bool) -> Path:
        return build_manifest(
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            model=model,
            stems=MODEL_STEMS[model],
            entries=entries,
            output_dir=out,
            complete=complete,
            expected_tracks=expected,
        )

    # Initial empty manifest so a frontend that's already polling sees the
    # ingest in progress (complete=false, tracks=[]).
    _write_manifest(complete=False)

    try:
        for i, track in enumerate(tracks, start=1):
            typer.echo(
                f"[{i}/{len(tracks)}] {track.title!r} — {', '.join(track.artists)}"
            )
            entry = _process_track(track, out, model, force_refresh)
            if entry is not None:
                entries.append(entry)
                # Incremental write: the frontend can pick up this track on
                # its next poll and start playing immediately.
                _write_manifest(complete=False)
    finally:
        # Always finalise — even on KeyboardInterrupt — so the frontend stops
        # polling and treats the partial result as the final playlist.
        manifest_path = _write_manifest(complete=True)
        typer.echo(
            f"\nDone. {len(entries)}/{expected} tracks have stems. "
            f"Manifest at {manifest_path}"
        )


def main() -> None:
    """Entry point referenced by ``[project.scripts] stemguessr = "stemguessr:main"``."""
    app()


if __name__ == "__main__":
    main()
