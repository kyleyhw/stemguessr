# StemGuessr Project Development Plan

This document outlines the planned phases and tasks for developing **StemGuessr** — a Bandle-style music-guessing game built around source-separated stems from a Spotify public playlist URL.

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

19. [pending] Add `httpx` as a dependency.
20. [pending] Implement iTunes Search API ISRC lookup (`/lookup?isrc=...&entity=song`).
21. [pending] Implement Deezer API ISRC fallback (`/track/isrc:{ISRC}`).
22. [pending] Implement disk cache (keyed by ISRC; deterministic file layout).
23. [pending] Implement HTTP download with retries and exponential backoff.
24. [pending] Write tests with mocked HTTP responses (success, miss, both-miss, network failure).
25. [pending] Write `docs/sources.md` covering source priority, cache layout, failure modes.

## Phase 4: Demucs Separation Wrapper

26. [pending] Add `demucs` as a dependency.
27. [pending] Implement Demucs wrapper (`htdemucs` default; `htdemucs_6s` opt-in via flag).
28. [pending] Make separation idempotent (skip if all stems already on disk).
29. [pending] Cache stem outputs to disk, organised by track ID and stem name.
30. [pending] Write tests with a small WAV fixture (synthetic mixture with known sources).
31. [pending] Write `docs/separation.md` with full Demucs algorithm derivation: hybrid time-domain / spectrogram U-Net, complex-mask parameterisation, L1 + multi-resolution STFT loss training objective, and the choice of `htdemucs` over baseline Demucs.

## Phase 5: Manifest Builder

32. [pending] Define `manifest.json` schema (versioned, JSON-Schema validated).
33. [pending] Implement manifest builder combining Spotify metadata and stem paths.
34. [pending] Write tests for schema validation (golden manifest fixture).
35. [pending] Write `docs/manifest.md` with the schema as the frontend contract.

## Phase 6: CLI Orchestration

36. [pending] Add `typer` as a dependency.
37. [pending] Implement `stemguessr ingest <playlist_url>` orchestrating Phases 2–5.
38. [pending] Add progress reporting (tracks done / total, current operation).
39. [pending] Add flags: `--out PATH`, `--stems {4,6}`, `--force-refresh`.
40. [pending] Write tests with mocked sub-modules.
41. [pending] Write `docs/cli.md` with full CLI reference.

## Phase 7: Frontend Scaffold

42. [pending] Create `web/index.html` (semantic markup, accessibility hooks).
43. [pending] Create `web/styles.css` — Fraunces + JetBrains Mono, cream/oxblood palette, late-night radio studio aesthetic.
44. [pending] Implement vanilla JS game state machine (4 rounds, stem reveal per round, guess input, win/lose).
45. [pending] Implement waveform visualisation (Web Audio API → canvas).
46. [pending] Implement manifest fetch and audio buffer preloading.
47. [pending] Add mock manifest fixture for offline frontend development.
48. [pending] Write `docs/frontend.md` describing the UI architecture and game state machine.

## Phase 8: Integration & Polish

49. [pending] End-to-end test: paste real Spotify playlist URL, run ingest, play game.
50. [pending] Error states: no previews available, network failures, partial coverage.
51. [pending] Cross-browser smoke test (Chromium primary; Firefox / Safari best-effort).
52. [pending] README finalisation with screenshots and quickstart.
53. [pending] Tag `v0.1.0` release.
