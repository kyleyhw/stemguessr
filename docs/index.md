# StemGuessr Documentation

This is the documentation hub for StemGuessr — a Bandle-style music-guessing game built around source-separated stems from a Spotify public playlist URL.

## Top-level documents

- [README](../README.md) — project overview, system architecture, repository layout, legal posture.
- [Project Plan](../PROJECT_PLAN.md) — phased development roadmap with live status tags.

## Per-phase documentation

These are written as each phase lands. Placeholders are listed below for navigability.

| Phase | Document | Status |
|-------|----------|--------|
| 2 | [`spotify.md`](spotify.md) — Spotify Web API integration, playlist parsing, ISRC extraction | written |
| 3 | [`sources.md`](sources.md) — preview lookup (iTunes / Deezer), caching, retry policy | written |
| 4 | [`separation.md`](separation.md) — Demucs algorithm derivation, hybrid waveform/spectrogram U-Net, training objective | written |
| 5 | [`manifest.md`](manifest.md) — `manifest.json` schema as the frontend contract | written |
| 6 | `cli.md` — `stemguessr ingest <playlist_url>` reference | _to be written_ |
| 7 | `frontend.md` — game UI architecture, state machine, waveform rendering | _to be written_ |

## Conventions

- Mathematics is presented in LaTeX. Inline `$...$`, display `$$...$$`. GitHub renders both.
- Citations are numbered, bracketed, in-line, and link to a "References" section at the end of each document. Format follows the user's CLAUDE.md citation convention.
- Visualisations include axis descriptions and an interpretation paragraph beneath them.
