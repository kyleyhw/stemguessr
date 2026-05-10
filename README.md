# StemGuessr

A music-guessing game in the Bandle / Heardle family, built around source-separated stems. Given a Spotify public playlist URL, the ingest pipeline pulls 30-second previews via the iTunes Search API (with Deezer as fallback), separates each clip into instrument stems with Demucs, and serves them to a static browser frontend that reveals one stem per round of guessing.

## Status

**v0.1.1 — 2026-05-10.** End-to-end verified: no Spotify credentials required, ingests a public playlist URL via the embed page, full Demucs separation, browser game with volume control. See [`CHANGELOG.md`](CHANGELOG.md) for the release log and [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the phased build log.

## System architecture

The pipeline has four stages: three off-line and one in the browser.

1. **Spotify Web API** (off-line, Client Credentials flow). Given a public playlist URL, fetch the track list with metadata: title, artist, duration, and the ISRC (`external_ids.isrc`). Spotify itself never returns raw audio.
2. **Preview source lookup** (off-line, public REST). For each ISRC, query Apple's iTunes Search API (`/lookup?isrc=...`) for a 30-second AAC `previewUrl`. On miss, fall back to Deezer (`/track/isrc:{ISRC}`) for a 30-second MP3. Combined coverage is essentially complete for any track on Spotify.
3. **Demucs source separation** (off-line, on-disk cache). Each cached preview is split into stems — by default `{drums, bass, vocals, other}` using `htdemucs`, optionally six stems via `htdemucs_6s` which adds `{guitar, piano}`.
4. **Static frontend** (browser). A single `index.html` fetches `manifest.json` and plays stems through `<audio>` elements. The game reveals one stem per round; the player has four guesses.

```
Spotify playlist URL
        │
        ▼
┌─────────────────────┐
│   Spotify Web API   │  ──►  list of tracks with ISRCs
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  iTunes ▶ Deezer    │  ──►  30 s preview MP3/AAC (cached on disk)
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  Demucs (htdemucs)  │  ──►  {drums, bass, vocals, other}.wav
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│    manifest.json    │  ──►  static frontend  ──►  game
└─────────────────────┘
```

## Source separation, briefly

Source separation is the inverse problem: given a mixture
$x(t) = \sum_{i=1}^{N} s_i(t)$, recover each source $s_i(t)$ for $i \in \{1, \dots, N\}$ where $N$ is the number of stems (4 or 6 here). The current state-of-the-art family — Hybrid Demucs (`htdemucs`) — is a U-Net with two parallel branches that exchange features at multiple depths:

- A **time-domain** 1-D convolutional branch that operates directly on the waveform $x(t)$.
- A **spectrogram-domain** 2-D branch that operates on the complex STFT $X(t, f) = \mathrm{STFT}\{x\}(t, f)$ and predicts complex-valued masks $M_i(t, f)$ for each source.

The two branch outputs are summed in the time domain to give the final source estimates $\hat{s}_i(t)$. The hybrid design is motivated by the empirical observation that some sources (drums, transients) are better separated in the time domain, while others (sustained tones, harmonic content) are better separated in the spectrogram domain.

A full derivation — including the training objective, mask parameterisation, and the choice of `htdemucs` over baseline Demucs — will be added in [`docs/separation.md`](docs/separation.md) when **Phase 4** lands.

## Repository layout

```
stemguessr/
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version
├── .secrets.baseline
├── CHANGELOG.md
├── LICENSE
├── PROJECT_PLAN.md
├── README.md            ← you are here
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── index.md         ← documentation hub
│   ├── spotify.md       ← Phase 2: Spotify ingest
│   ├── sources.md       ← Phase 3: preview sources
│   ├── separation.md    ← Phase 4: Demucs derivation
│   ├── manifest.md      ← Phase 5: manifest schema
│   ├── cli.md           ← Phase 6: CLI reference
│   └── frontend.md      ← Phase 7: frontend architecture
├── src/
│   └── stemguessr/
│       ├── __init__.py  ← package root (re-exports cli.main)
│       ├── spotify.py   ← Phase 2: Spotify Web API client
│       ├── sources.py   ← Phase 3: iTunes/Deezer preview lookup
│       ├── separate.py  ← Phase 4: Demucs separation wrapper
│       ├── manifest.py  ← Phase 5: manifest.json builder
│       └── cli.py       ← Phase 6: stemguessr ingest <url>
├── tests/
│   ├── __init__.py
│   ├── test_spotify.py
│   ├── test_sources.py
│   ├── test_separate.py
│   ├── test_manifest.py
│   ├── test_cli.py
│   ├── test_fixture_manifest.py
│   └── reports/
│       ├── phase2_spotify.md
│       ├── phase3_sources.md
│       ├── phase4_separate.md
│       ├── phase5_manifest.md
│       ├── phase6_cli.md
│       ├── phase7_frontend.md
│       └── phase8_release.md
└── web/                 ← Phase 7 frontend
    ├── index.html
    ├── styles.css
    ├── game.js
    └── fixtures/
        └── manifest.json
```

## Documentation

- [`docs/index.md`](docs/index.md) — documentation hub.
- [`docs/spotify.md`](docs/spotify.md) — Spotify Web API integration, playlist parsing, ISRC extraction.
- [`docs/sources.md`](docs/sources.md) — preview lookup (iTunes / Deezer), caching, retry policy.
- [`docs/separation.md`](docs/separation.md) — Demucs algorithm derivation, hybrid waveform/spectrogram U-Net, training objective.
- [`docs/manifest.md`](docs/manifest.md) — `manifest.json` schema as the frontend contract.
- [`docs/cli.md`](docs/cli.md) — `stemguessr ingest <playlist_url>` reference.
- [`docs/frontend.md`](docs/frontend.md) — game UI architecture, state machine, waveform rendering.
- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) — phased development plan with status tags.
- [`CHANGELOG.md`](CHANGELOG.md) — release notes.

## Quickstart

End-to-end: clone, install, ingest a public playlist, copy the static frontend assets next to the cache, and serve. **No Spotify credentials are required** — playlist data and preview URLs come from Spotify's public embed page.

```bash
# 1. Clone and install (Python 3.12+ required; uv will fetch if missing)
git clone https://github.com/kyleyhw/stemguessr.git
cd stemguessr
uv sync

# 2. Ingest a public playlist. The first run downloads ~250 MB of Demucs
#    weights and runs CPU separation (~5-15 s per 30 s clip on CPU); later
#    runs over the same playlist are essentially instant (cache hit). Use
#    --limit N for a quick smoke test against a large playlist.
uv run stemguessr ingest \
    "https://open.spotify.com/playlist/<id>" \
    --out ./cache \
    --limit 5

# 3. Copy frontend assets next to the manifest and serve.
cp web/index.html web/styles.css web/game.js ./cache/
cd ./cache
python -m http.server 8000

# 4. Open http://localhost:8000/ in a Chromium-based browser.
```

## Development

The project uses **uv** for package and environment management, **ruff** for linting and formatting, **ty** for type-checking, and **detect-secrets** for pre-commit secret scanning. All four are wired through `pre-commit`.

```bash
# Install dev tooling and pre-commit hooks
uv sync --all-groups
uv run pre-commit install

# Run hooks against all files
uv run pre-commit run --all-files

# Run the test suite (72 tests, fully offline)
uv run pytest
```

## Legal posture

- The repository contains **code only**. No audio is committed, ever.
- Users supply their own Spotify public playlist URL. No Spotify Premium account is required for ingestion (Client Credentials flow is sufficient for public playlist metadata).
- Audio is fetched at runtime from public preview endpoints (iTunes Search API; Deezer public API). These previews are not redistributed by this project; they are downloaded into a local on-disk cache for the user's own use.
- Users are responsible for compliance with the terms of the third-party APIs they query through this tool.

## License

[MIT](LICENSE).
