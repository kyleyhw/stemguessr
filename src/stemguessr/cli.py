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

import dataclasses
import random
import shutil
from collections.abc import Callable
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
    fetch_track_cover_url,
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

    # Best-effort cover-art fetch via Spotify oEmbed. Failure is silently
    # tolerated — the manifest will record cover_url=None and the frontend
    # falls back to its plain "title + artists" reveal.
    cover_url = track.cover_url or fetch_track_cover_url(track.spotify_id)
    track_with_cover = dataclasses.replace(track, cover_url=cover_url)

    stem_dir = cache_dir / "stems" / track_id
    stem_paths = separate(preview_path, stem_dir, model=model)
    return TrackBuildEntry(track=track_with_cover, stem_paths=stem_paths)


def run_ingest_pipeline(
    playlist_url: str,
    cache_dir: Path,
    *,
    n_stems: int = 4,
    limit: int | None = None,
    force_refresh: bool = False,
    log: Callable[[str], None] = lambda _: None,
) -> Path:
    """Run the ingest end-to-end pipeline: fetch playlist → for each track,
    download the preview and separate it → write manifest progressively.

    Used by both the ``ingest`` CLI command and the HTTP server. ``log`` is
    called with one line per progress event; pass ``typer.echo`` from the
    CLI, or a thread-safe printer from the server.

    Returns the path of the final ``manifest.json`` (with ``complete=True``).
    The manifest is also rewritten with ``complete=False`` after every
    successful track separation, so a polling frontend can pick up tracks
    as they land.

    Raises:
        SpotifyError: URL parse failure or playlist fetch failure.
        ValueError: ``n_stems`` is not 4 or 6.
    """
    model = _model_for_stems(n_stems)
    playlist_id = parse_playlist_id(playlist_url)

    log(f"Fetching tracks for playlist {playlist_id}...")
    tracks = fetch_playlist_tracks(playlist_url)

    if limit is not None:
        tracks = tracks[:limit]
        log(f"  {len(tracks)} tracks (limited from playlist by --limit).")
    else:
        log(f"  {len(tracks)} tracks found.")

    # Shuffle the processing order (on a copy, so the caller's list is not
    # mutated). The manifest is written progressively and the frontend
    # appends tracks in arrival order — its own shuffle only covers tracks
    # present at the first fetch — so ingestion order IS the effective play
    # order during a live ingest. Without this, the first playable track
    # would always be the playlist's first track. Shuffling after the
    # --limit slice preserves that flag's "first N tracks" semantics.
    tracks = list(tracks)
    random.shuffle(tracks)
    log("  processing order shuffled.")

    expected = len(tracks)
    entries: list[TrackBuildEntry] = []

    def _write_manifest(*, complete: bool) -> Path:
        return build_manifest(
            playlist_id=playlist_id,
            playlist_url=playlist_url,
            model=model,
            stems=MODEL_STEMS[model],
            entries=entries,
            output_dir=cache_dir,
            complete=complete,
            expected_tracks=expected,
        )

    _write_manifest(complete=False)

    try:
        for i, track in enumerate(tracks, start=1):
            log(f"[{i}/{len(tracks)}] {track.title!r} — {', '.join(track.artists)}")
            entry = _process_track(track, cache_dir, model, force_refresh)
            if entry is not None:
                entries.append(entry)
                _write_manifest(complete=False)
    finally:
        manifest_path = _write_manifest(complete=True)
        log(
            f"Done. {len(entries)}/{expected} tracks have stems. "
            f"Manifest at {manifest_path}"
        )
    return manifest_path


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
        run_ingest_pipeline(
            playlist_url,
            out,
            n_stems=n_stems,
            limit=limit,
            force_refresh=force_refresh,
            log=typer.echo,
        )
    except (ValueError, SpotifyError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def serve(
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            "-o",
            help="Cache root directory the server reads from and writes into.",
        ),
    ] = Path("./cache"),
    host: Annotated[
        str,
        typer.Option(
            "--host", help="Bind address. Default 127.0.0.1 (localhost-only)."
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="TCP port to listen on."),
    ] = 8765,
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            help="Do not open the game in the default browser on startup.",
        ),
    ] = False,
) -> None:
    """Run the StemGuessr web server.

    Hosts the static frontend, serves the cache contents, and exposes
    ``POST /api/ingest`` so the browser can paste a Spotify playlist URL
    and start ingest without going back to the terminal. Opens the game
    in the default browser unless ``--no-browser`` is given.
    """
    from stemguessr.server import serve_forever

    out.mkdir(parents=True, exist_ok=True)
    typer.echo(f"StemGuessr serving on http://{host}:{port}/")
    typer.echo("Open the URL, paste a public Spotify playlist URL, and play.")
    typer.echo("Press Ctrl-C to stop.")
    serve_forever(
        cache_dir=out,
        host=host,
        port=port,
        log=typer.echo,
        open_browser=not no_browser,
    )


def main() -> None:
    """Entry point referenced by ``[project.scripts] stemguessr = "stemguessr:main"``."""
    app()


if __name__ == "__main__":
    main()
