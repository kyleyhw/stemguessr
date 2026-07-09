# StemGuessr Project Development Plan

This document outlines the planned phases and tasks for developing **StemGuessr** — a music-guessing game built around source-separated stems from a Spotify public playlist URL.

Status tags: `[completed]`, `[in-progress]`, `[pending]`. Updated live as work progresses.

## Phase 1: Repo Skeleton & Tooling

1.  [completed] Rename branch `master` → `main`.
2.  [completed] Remove PyCharm boilerplate (`main.py`).
3.  [completed] Initialise uv package (`uv init --package --python 3.12`).
4.  [completed] Write `.gitignore` (Python, virtual envs, IDE, OS metadata, audio caches, Demucs models).
5.  [completed] Add dev dependencies: `ruff`, `ty`, `detect-secrets`, `pre-commit`.
6.  [completed] Write `.pre-commit-config.yaml` (ruff + ruff-format + detect-secrets + ty hooks).
7.  [completed] Create directory scaffolding: `docs/`, `tests/`, `tests/reports/`, `web/`.
8.  [completed] Write `README.md` (project description, system overview, ASCII tree, doc index, Demucs algorithmic frame, legal posture).
9.  [completed] Write `PROJECT_PLAN.md` (this file).
10. [completed] Generate `.secrets.baseline` via detect-secrets.
11. [completed] Install pre-commit hooks; verify clean run on all files.
12. [completed] Initial commit and push to `origin/main`.

## Phase 2: Spotify Ingest Module

13. [completed] Add `spotipy` as a dependency.
14. [completed] Implement Spotify Web API client (Client Credentials flow).
15. [completed] Implement playlist URL parser (extract playlist ID from various URL forms: `open.spotify.com/playlist/...`, `spotify:playlist:...`, full URI with query string).
16. [completed] Implement track listing extractor (titles, artists, ISRCs, durations, paginated for >100 tracks).
17. [completed] Write unit tests for parser and extractor (mocked HTTP).
18. [completed] Write `docs/spotify.md` covering API contract, auth model, rate limits, error handling.

## Phase 3: Preview Source Lookup & Download

19. [completed] Add `httpx` as a dependency.
20. [completed] Implement iTunes Search API ISRC lookup (`/lookup?isrc=...&entity=song`).
21. [completed] Implement Deezer API ISRC fallback (`/track/isrc:{ISRC}`).
22. [completed] Implement disk cache (keyed by ISRC; deterministic file layout).
23. [completed] Implement HTTP download with retries and exponential backoff.
24. [completed] Write tests with mocked HTTP responses (success, miss, both-miss, network failure).
25. [completed] Write `docs/sources.md` covering source priority, cache layout, failure modes.

## Phase 4: Demucs Separation Wrapper

26. [completed] Add `demucs` as a dependency.
27. [completed] Implement Demucs wrapper (`htdemucs` default; `htdemucs_6s` opt-in via flag).
28. [completed] Make separation idempotent (skip if all stems already on disk).
29. [completed] Cache stem outputs to disk, organised by track ID and stem name.
30. [completed] Write tests with a mocked Demucs seam (real-Demucs end-to-end deferred to Phase 8 behind an env-var opt-in).
31. [completed] Write `docs/separation.md` with full Demucs algorithm derivation: hybrid time-domain / spectrogram U-Net, complex-mask parameterisation, L1 + multi-resolution STFT loss training objective, and the choice of `htdemucs` over baseline Demucs.

## Phase 5: Manifest Builder

32. [completed] Define `manifest.json` schema (versioned, version 1).
33. [completed] Implement manifest builder combining Spotify metadata and stem paths.
34. [completed] Write tests for schema invariants (8 tests covering happy path, ID fallback, error paths, ordering, empty playlist).
35. [completed] Write `docs/manifest.md` with the schema as the frontend contract.

## Phase 6: CLI Orchestration

36. [completed] Add `typer` as a dependency.
37. [completed] Implement `stemguessr ingest <playlist_url>` orchestrating Phases 2–5.
38. [completed] Add progress reporting (tracks done / total, current operation).
39. [completed] Add flags: `--out PATH`, `--stems {4,6}`, `--force-refresh`.
40. [completed] Write tests with mocked sub-modules (7 tests via typer.testing.CliRunner).
41. [completed] Write `docs/cli.md` with full CLI reference.

## Phase 7: Frontend Scaffold

42. [completed] Create `web/index.html` (semantic markup, ARIA hooks).
43. [completed] Create `web/styles.css` — Fraunces + JetBrains Mono, cream/oxblood palette, late-night radio studio aesthetic.
44. [completed] Implement vanilla JS game state machine (rounds reveal stems cumulatively, guess input, win/lose, reveal).
45. [completed] Implement waveform visualisation (Web Audio API → canvas, per-pixel min/max plot with playback cursor).
46. [completed] Implement manifest fetch and audio buffer preloading (per-track decode into AudioBuffer cache).
47. [completed] Add mock manifest fixture for offline frontend development (`web/fixtures/manifest.json`).
48. [completed] Write `docs/frontend.md` describing the UI architecture and game state machine.

## Phase 8: Integration & Polish

49. [deferred] End-to-end test against a real Spotify playlist (deferred — requires API credentials; documented procedure in `tests/reports/phase8_release.md`).
50. [completed] Error states covered by unit tests across phases 2–6 (no preview / no ISRC / network failure / partial coverage / both-source miss).
51. [deferred] Cross-browser smoke test (deferred — manual fixture-based smoke completed in Phase 7; Playwright deferred to v0.2.0).
52. [completed] README finalisation: Quickstart section with concrete commands, full doc index, license reference, status banner.
53. [completed] Add `--version` flag, `LICENSE` (MIT), `CHANGELOG.md`; tag `v0.1.0`.

## Phase 9: Distribution, Reset & Score Tracker (v0.2.0)

54. [completed] Self-contained package: move `web/` → `src/stemguessr/web/` so the wheel ships the frontend; resolve via `Path(__file__).parent / "web"` in `server.py`.
    - [completed] Relocate the dev fixture to `tests/fixtures/manifest.json` (test asset — must not ship in the wheel).
    - [completed] Build wheel; verify static assets are included and `DEFAULT_WEB_DIR` resolves from an installed wheel.
55. [in-progress] Zero-hassle launch for friends' machines (all processing stays local):
    - [completed] Symmetric one-download, one-click launchers: `run.bat` (Windows) and `run.command` (macOS, exec bit set in git); `serve` opens the browser itself once the socket is bound (`--no-browser` opts out). `.gitattributes` pins per-script line endings.
    - [completed] One-click uninstallers `uninstall.bat` / `uninstall.command` (app-local always; shared uv/torch caches on confirmation).
    - [completed] GitHub Actions trusted-publishing workflow (`.github/workflows/publish.yml`) for PyPI releases.
    - [completed] `docs/distribution.md` + README quickstart (double-click model + `uvx stemguessr serve` terminal alternative).
    - [pending] PyPI project creation + trusted-publisher registration (manual, owner-only step) and first `v0.2.0` GitHub release.
60. [completed] Favicon: waveform-mark SVG served at `/favicon.svg` and declared via `<link rel="icon">`, removing the default `/favicon.ico` 404.
56. [completed] Reset workflow: `POST /api/reset` cancels any in-flight ingest (cooperative between-track, join-before-delete), then clears `manifest.json`, `stems/`, `previews/`; frontend `↺ reset` chip with are-you-sure confirmation returning to the playlist form; `tests/test_server.py` + `tests/test_cli.py` cancellation tests.
57. [completed] Score tracker: per-track outcomes recorded at reveal (solved-at-stage-k or missed); `score n/m` chip with hover-expand panel grouping songs by solve stage. UI delta limited to a two-chip top-right cluster.
58. [completed] Enter mirrors the primary action: reveal card advances to the next track on Enter (forms already submit natively).
59. [completed] Docs, CHANGELOG 0.2.0, version bump, test report, Playwright end-to-end verification (game flow unchanged; reset and score exercised in a scratch cache).
