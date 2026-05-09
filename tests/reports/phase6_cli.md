# Phase 6 Test Report — CLI Orchestration

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Module under test | `stemguessr.cli` |
| Test file | `tests/test_cli.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **7 passed** |
| Total runtime | **0.57 s** |

## What was tested and why

The CLI is the only code that *composes* the Phase 2–5 modules. Each underlying stage is unit-tested in isolation; what the CLI tests verify is that the orchestration logic is correct: arguments are validated before any pipeline work begins, exit codes encode the right outcome, missing data is skipped without aborting, and `--force-refresh` actually deletes cached state.

All four stages (`get_client`, `fetch_playlist_tracks`, `get_preview`, `separate`) are monkeypatched at the `stemguessr.cli` import boundary. The CLI is invoked through `typer.testing.CliRunner` so the test runs in-process without subprocesses.

### Argument validation (2 tests)

- *Invalid `--stems`*. Passing `--stems 5` is rejected before any Spotify call; exit code 1; stderr contains "must be 4 or 6". This is the cheapest place to fail and the message must be actionable.
- *Invalid playlist URL*. A clearly-not-a-URL string is fed to the parser; exit code 1; stderr message is the parser's own error. Same fail-fast principle: never call out to Spotify if the URL won't parse.

### Happy path (2 tests)

- *Manifest is written*. With two stub tracks, default `--out`, default 4-stem mode: exit 0, `manifest.json` written, with the right `model` and 2 entries in `tracks[]`. End-to-end smoke test of the orchestration.
- *`--stems 6` plumbs through*. Same setup with `--stems 6`. Verifies (a) typer accepts the value, (b) `_model_for_stems` returns `htdemucs_6s`, (c) every per-track call to the stub `separate` receives `model="htdemucs_6s"`. This is the load-bearing assertion that the model selection isn't silently lost between layers.

### Skipping (2 tests)

The pipeline must continue past per-track failures rather than aborting; otherwise a single missing ISRC bricks an entire playlist ingest.

- *Track with `isrc=None`*. Two tracks, second has `isrc=None`. Exit 0; "no ISRC" appears in stderr; manifest contains 1 track (the survivor) by Spotify ID.
- *Track with no preview*. Two tracks; the first ISRC's `get_preview` is stubbed to return `None`. Exit 0; "no preview source has" in stderr; manifest contains 1 track.

### Force refresh (1 test)

A pre-existing `cache/previews/{ISRC}.m4a` and `cache/stems/{ISRC}/drums.wav` are seeded with the byte string `b"STALE"`. After `stemguessr ingest --force-refresh`, both files exist but contain non-stale bytes — the orchestrator deleted them, the stub re-wrote them. Verifies `_clear_track_cache` is actually called per track when the flag is set.

## Failures

None at final run. One fix made during development: typer with a single `@app.command()` promotes it to root (so the user-facing invocation would be `stemguessr <url>` not `stemguessr ingest <url>`). Adding an empty `@app.callback()` forces subcommand mode, matching the documented CLI surface.

## Reproduction

```bash
uv run pytest tests/test_cli.py -v
```
