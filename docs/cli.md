# StemGuessr CLI Reference

This document describes the command-line interface implemented in [`src/stemguessr/cli.py`](../src/stemguessr/cli.py): the orchestration layer that composes Phases 2–5 into a single user-facing command.

## Synopsis

```
stemguessr ingest <playlist_url> [--out PATH] [--stems {4,6}] [--force-refresh]
```

`stemguessr` is registered as a console script in `pyproject.toml`. After `uv sync` (or `pip install`), it is on the `PATH`.

## What `ingest` does

```
Spotify playlist URL
        │
        ▼
[ parse_playlist_id ]            (Phase 2 — pure function)
        │
        ▼
[ Spotify Web API ]              (Phase 2 — needs SPOTIFY_CLIENT_ID/SECRET)
        │
        ▼
   for each track:
        ├── skip if no ISRC
        ├── (optional) clear cached preview/stems if --force-refresh
        ├── get_preview(isrc) →   (Phase 3 — iTunes / Deezer)
        │       skip if both miss
        └── separate(preview)  →  (Phase 4 — Demucs)
        ▼
[ build_manifest(entries) ]      (Phase 5)
        │
        ▼
   manifest.json + stems/<id>/*.wav under --out
```

The whole pipeline is a single linear function; per-track failures (no ISRC, no preview source has it) are reported on stderr and skipped without aborting the run.

## Arguments

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `playlist_url` | string | yes | — | Any of the URL/URI forms parsed by [`parse_playlist_id`](spotify.md#playlist-url-parsing). |
| `--out` / `-o` | path | no | `./cache` | Cache root — receives `previews/`, `stems/`, `manifest.json`. Created if missing. |
| `--stems` | int | no | `4` | `4` (htdemucs) or `6` (htdemucs_6s). Any other value → exit code 1. |
| `--force-refresh` | bool | no | `false` | Delete cached preview and stem files for **every** track in the playlist before re-processing. |

## Required environment variables

```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
```

The Client Credentials flow is sufficient for any *public* playlist. Register an application at <https://developer.spotify.com/dashboard>.

## Output layout

After a successful run with `--out ./cache`:

```
cache/
├── manifest.json            ← frontend reads this
├── previews/
│   └── {ISRC}.{m4a|mp3}     ← Phase 3 cache; not referenced by manifest
└── stems/
    └── {ISRC}/
        ├── drums.wav
        ├── bass.wav
        ├── vocals.wav
        └── other.wav        ← (+ guitar.wav, piano.wav for --stems 6)
```

The frontend (Phase 7) is configured to serve `cache/` as its static root, so the relative URLs in the manifest resolve directly as static-asset paths.

## Exit codes

| Code | Cause |
|------|-------|
| `0` | Successful ingest. Manifest written. |
| `1` | Bad input: invalid `--stems`, unparseable playlist URL, or missing Spotify credentials. |
| `≥ 2` | Unexpected exception (network failure that survived retries, Demucs crash, disk full). The traceback is propagated unmodified. |

A run with one or more skipped tracks (no ISRC, no preview source) still exits `0`. The skip is a normal data outcome, not an error.

## Idempotency and `--force-refresh`

By design, the pipeline is idempotent. On a second run over the same playlist:

- **Previews** are cache-hit at Phase 3 (existing file → no network call).
- **Stems** are cache-hit at Phase 4 (all expected stem files exist → no Demucs call).
- The manifest is rewritten unconditionally, with the current build timestamp.

Re-running is therefore essentially free, and is the recommended way to rebuild the manifest after adding tracks to the source playlist.

`--force-refresh` overrides this by clearing the cache entries for every track in the *current* playlist before processing. Tracks that are no longer in the playlist are not touched (their orphaned cache entries persist; users can `rm -rf cache/{stems,previews}` for a hard reset).

## Examples

```bash
# Default: 4 stems, cache in ./cache.
stemguessr ingest "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

# 6-stem mode (separates guitar/piano from "other").
stemguessr ingest \
    "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M" \
    --stems 6 \
    --out ./my_cache

# Re-ingest after model upgrade.
stemguessr ingest "..." --force-refresh
```

## Testing

Tests in [`tests/test_cli.py`](../tests/test_cli.py) use `typer.testing.CliRunner` to invoke the app in-process. Every pipeline stage is monkeypatched at the `stemguessr.cli` import boundary, so the tests exercise orchestration logic alone (argument validation, exit codes, skip-on-miss, force-refresh side effects).

Coverage:

- Bad `--stems` value → exit code 1, error on stderr.
- Bad playlist URL → exit code 1, error on stderr.
- Happy path → manifest with both tracks, model field set correctly.
- `--stems 6` → separate called with `htdemucs_6s` per track.
- Track with `isrc=None` → reported and skipped, manifest contains only the survivor.
- Track with no preview from any source → reported and skipped.
- `--force-refresh` → stale cached preview and stem files are overwritten.

Run the tests:

```bash
uv run pytest tests/test_cli.py -v
```

The latest test report is at [`../tests/reports/phase6_cli.md`](../tests/reports/phase6_cli.md).
