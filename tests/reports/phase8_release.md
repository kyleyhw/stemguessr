# Phase 8 Test Report — Integration, Polish, and Release

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Release tag | **v0.1.0** |
| Full suite | **72 passed** in 0.87 s (offline) |
| Modules | `stemguessr.spotify`, `stemguessr.sources`, `stemguessr.separate`, `stemguessr.manifest`, `stemguessr.cli`, `web/*`, fixture manifest |

## What this phase verified

Phase 8 is the integration boundary: it does not introduce new source modules, but it adds the `--version` flag, license metadata, changelog, and the README quickstart, and it confirms that the assembled vertical slice is shippable.

### Automated coverage

The full suite of 72 unit tests was re-run and passes cleanly:

| Phase | Tests | Module |
|-------|-------|--------|
| 2 | 25 | `stemguessr.spotify` |
| 3 | 16 | `stemguessr.sources` |
| 4 | 8 | `stemguessr.separate` |
| 5 | 8 | `stemguessr.manifest` |
| 6 | 8 | `stemguessr.cli` (incl. new `--version`) |
| 7 | 7 | fixture manifest schema |
| **Total** | **72** | |

All tests run offline. HTTP via `httpx.MockTransport`; Spotify and Demucs mocked at import boundaries; `time.sleep` patched to a no-op so retry-backoff paths run instantly.

### `--version` flag (1 new test)

`stemguessr --version` prints `stemguessr <version>` (sourced via `importlib.metadata.version("stemguessr")`) and exits 0. Verified by `tests/test_cli.py::TestVersion::test_version_flag_prints_version_and_exits` and by direct invocation:

```
$ uv run stemguessr --version
stemguessr 0.1.0
```

### Error states (Plan task 50)

These are covered by unit tests across phases:

| Error | Module | Test |
|-------|--------|------|
| Empty / malformed playlist URL | spotify | `test_invalid_forms_raise[*]` (10 cases) |
| Missing Spotify credentials | spotify | `test_missing_credentials_raises` |
| Partial Spotify credentials | spotify | `test_partial_credentials_raise` |
| Track without ISRC | cli | `test_track_without_isrc_is_skipped` |
| iTunes empty results | sources | `test_miss_empty_results` |
| iTunes hit but no `previewUrl` | sources | `test_miss_no_preview_url` |
| iTunes non-JSON response | sources | `test_non_json_raises_source_error` |
| Deezer 200 + `error` object | sources | `test_miss_via_error_object` |
| Deezer 4xx | sources | `test_miss_via_4xx` |
| Deezer 5xx (after retries) | sources | `test_5xx_propagates` |
| Both sources miss | cli + sources | `test_returns_none_when_both_sources_miss`, `test_track_with_no_preview_is_skipped` |
| 429 with Retry-After | sources | `test_429_then_success` |
| Transient network failure | sources | `test_network_error_recovers` |
| Retries exhausted | sources | `test_exhausts_retries_then_raises` |
| Atomic-write contract on download failure | sources | `test_atomic_write_no_partial_file` |
| Unknown Demucs model | separate | `test_unknown_model_raises` |
| Missing input file | separate | `test_missing_input_raises` |
| Manifest entry missing stem | manifest | `test_missing_stem_raises` |
| Stem path outside `output_dir` | manifest | `test_path_outside_output_dir_raises` |
| Bad `--stems` count | cli | `test_invalid_stems_count_exits_1` |
| Manifest version mismatch | frontend | manual smoke (Phase 7) |
| Manifest fetch 404 | frontend | manual smoke (Phase 7) |

### Deferred to manual / future runs

Two Plan items are explicitly deferred — both because they require runtime resources I cannot wire up from the CLI and pytest alone:

#### Task 49 — Live-Spotify end-to-end run

Procedure for the maintainer to execute:

```bash
# Set credentials.
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."

# Pick a small playlist (≤ 10 tracks) for the first run; first track triggers
# the ~250 MB Demucs model download.
uv run stemguessr ingest "https://open.spotify.com/playlist/<id>" --out ./cache

# Verify outputs.
ls cache/manifest.json
ls cache/previews/
ls cache/stems/

# Copy frontend assets and serve.
cp web/index.html web/styles.css web/game.js ./cache/
cd ./cache
python -m http.server 8000
# Open http://localhost:8000/ in Chromium; play through one track.
```

Expected outcomes:

- `manifest.json` exists with `version: 1` and `tracks.length` ≥ 1.
- `cache/previews/<ISRC>.{m4a|mp3}` exist for every track that had an ISRC and a preview source.
- `cache/stems/<ISRC>/{drums,bass,vocals,other}.wav` exist per separated track.
- Browser console: no JavaScript errors; status line shows track count.
- Audio plays per round; correct guess transitions to reveal; reveal shows real title and artists.

#### Task 51 — Cross-browser smoke

Manual checklist for the maintainer:

- **Chromium / Edge.** Primary target. Web Audio + AudioBufferSourceNode + Canvas all green.
- **Firefox.** Same code paths; `webkitAudioContext` fallback unused. Verify audio plays.
- **Safari.** `webkitAudioContext` fallback engaged. AudioContext may need a user-gesture resume on mobile Safari (already handled by `audioCtx.resume()` in `play()`).

A Playwright suite covering the round-by-round game loop is tracked for v0.2.0.

## What v0.1.0 contains

- Spotify ingest, preview lookup, Demucs separation, manifest builder, CLI orchestration, vanilla-JS frontend.
- 72 offline unit tests, full pre-commit (ruff + ty + detect-secrets).
- Per-phase docs, README quickstart, MIT license, CHANGELOG.

## Reproduction

```bash
uv run pytest               # 72 tests, ~0.9 s
uv run stemguessr --version # stemguessr 0.1.0
```
