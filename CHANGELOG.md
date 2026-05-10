# Changelog

All notable changes to StemGuessr are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-05-10

End-to-end UI verification, no-auth ingest, volume control. The pipeline now runs against a public Spotify playlist URL with **zero credentials configured**, and was exercised end-to-end against `Top 50 - Global` (limited to 2 tracks for the verification run).

### Changed

- **Spotify ingest is now embed-based, no authentication required.** `stemguessr.spotify` parses the public `open.spotify.com/embed/playlist/<id>` page and extracts the `__NEXT_DATA__` JSON payload that Spotify renders for its React client. Each track in the embed already carries a direct 30-second MP3 preview URL (`audioPreview.url` on Spotify's `p.scdn.co` CDN), so the iTunes/Deezer ISRC-based detour is no longer the default path.
- `Track` dataclass gains a `preview_url: str | None` field. `isrc` is retained but is always `None` on the embed path. `id` resolution falls back from ISRC to Spotify ID for manifest stability.
- `stemguessr.sources.download_preview(url, cache_key, cache_dir)` added — direct download with caching, used when the metadata source already gives us the URL. `get_preview` (ISRC-based, with iTunes/Deezer lookup + retries) is retained as an alternate path.
- `stemguessr.separate._run_demucs` rewritten on Demucs's lower-level `apply_model` + `pretrained.get_model` API (the higher-level `demucs.api.Separator` is only present in 4.1+). Audio loading switched from `torchaudio.load` (which now requires `torchcodec` + system FFmpeg) to `soundfile` (libsndfile-backed, MP3-capable on its bundled wheel).

### Added

- **`--limit N`** flag on `stemguessr ingest` for quick smoke tests against large playlists.
- **Volume slider** in the frontend. A master `GainNode` sits between every source and `audioCtx.destination`; the slider drives its `gain.value`. Default volume `0.1`, slider range `0..0.25`. Earlier sessions clipped because every stem connected directly to the destination at unity gain.

### Removed

- `stemguessr.spotify.get_client` — Client Credentials flow is no longer the default. Set `SPOTIFY_CLIENT_ID/SECRET` no longer does anything; remove from your environment if previously set for this project.

### Fixed

- `parse_playlist_id` now also accepts a bare 22-char playlist ID (it was previously URL/URI-only).
- GitHub default branch on the remote: `master` → `main`.

### Verified

- 79 unit tests pass offline (up from 72 in 0.1.0).
- End-to-end Playwright run against `https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF`: ingest of 2 tracks, separation completes, manifest written, both tracks playable through the frontend, win-on-round-1 and win-on-round-3-after-skip flows both render correct reveals.

## [0.1.0] — 2026-05-10

Initial alpha release. Complete vertical slice from Spotify URL to playable game.

### Added

- **Spotify ingest** (`stemguessr.spotify`). Client Credentials flow, playlist URL/URI parser accepting four URL forms, paginated track listing with ISRC extraction, null-track skip semantics.
- **Preview source lookup** (`stemguessr.sources`). iTunes Search API as priority-1 source (M4A), Deezer public API as fallback (MP3). ISRC-keyed disk cache, atomic temp-file + rename downloads, exponential-backoff retry on 429 / network failures / 5xx.
- **Demucs separation wrapper** (`stemguessr.separate`). `htdemucs` (4-stem) default, `htdemucs_6s` (6-stem) opt-in; idempotent by file existence, lazy torch / demucs / torchaudio imports.
- **Manifest builder** (`stemguessr.manifest`). Schema v1 producing `manifest.json` as the contract between ingest pipeline and frontend; POSIX-relative stem URLs, ID falls back from ISRC to Spotify ID, validation of stem completeness.
- **CLI orchestration** (`stemguessr.cli`). `stemguessr ingest <playlist_url>` end-to-end, with `--out`, `--stems {4,6}`, `--force-refresh`, `--version`. Per-track skip-on-miss; idempotent re-runs.
- **Frontend** (`web/`). Single static HTML / CSS / vanilla-JS-module; Web Audio API source-graph playback per round; per-pixel min/max waveform visualisation with playback cursor; title-only fuzzy answer matching.
- **Documentation** (`docs/`). Per-phase technical write-ups: `spotify.md`, `sources.md`, `separation.md` (with Demucs derivation: hybrid time-frequency U-Net, HT transformer extension, L1 + multi-resolution STFT loss), `manifest.md`, `cli.md`, `frontend.md`.
- **Test suite**. 72 unit tests, all offline (HTTP via `httpx.MockTransport`; Spotify, Demucs mocked at import boundaries). Per-phase test reports under `tests/reports/`.
- **Tooling**. `uv` for packaging; `ruff` lint and format; `ty` type-checking; `detect-secrets` baseline; `pre-commit` wiring all four. `.gitignore` covers Python, IDE, venv, audio caches, model weights.
- **License**. MIT.

### Known limitations

- 30-second source audio (iTunes / Deezer preview cap) → 30 s of separated stems.
- 128 kbps source compression → audible Demucs artefacts on `vocals` and `other`.
- `--force-refresh` clears caches only for tracks in the current playlist; orphans persist.
- No `stemguessr serve` command yet — frontend assets must be copied next to `manifest.json` and served manually.
- No automated end-to-end test against live Spotify (requires API credentials).
- No automated browser tests yet (Playwright deferred).

### Tracked for v0.2.0

- `stemguessr serve` to launch the frontend.
- Daily-challenge mode with deterministic shuffle seeded by date.
- Per-stem volume sliders.
- Artist-name credit in answer-checking (opt-in).
