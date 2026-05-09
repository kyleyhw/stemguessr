# StemGuessr

A music-guessing game in the Bandle / Heardle family, built around source-separated stems. Given a Spotify public playlist URL, the ingest pipeline pulls 30-second previews via the iTunes Search API (with Deezer as fallback), separates each clip into instrument stems with Demucs, and serves them to a static browser frontend that reveals one stem per round of guessing.

## Status

In active development. See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the phased roadmap. The repository currently completes **Phase 1: Repo Skeleton & Tooling** — no game logic yet.

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
├── PROJECT_PLAN.md
├── README.md            ← you are here
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── index.md         ← documentation hub
│   ├── spotify.md       ← Phase 2: Spotify ingest
│   ├── sources.md       ← Phase 3: preview sources
│   └── separation.md    ← Phase 4: Demucs derivation
├── src/
│   └── stemguessr/
│       ├── __init__.py  ← package root (CLI entry in Phase 6)
│       ├── spotify.py   ← Phase 2: Spotify Web API client
│       ├── sources.py   ← Phase 3: iTunes/Deezer preview lookup
│       └── separate.py  ← Phase 4: Demucs separation wrapper
├── tests/
│   ├── __init__.py
│   ├── test_spotify.py
│   ├── test_sources.py
│   ├── test_separate.py
│   └── reports/
│       ├── phase2_spotify.md
│       ├── phase3_sources.md
│       └── phase4_separate.md
└── web/                 ← frontend, populated in Phase 7
```

## Documentation

- [`docs/index.md`](docs/index.md) — documentation hub, links to per-phase docs as they land.
- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) — phased development plan with status tags.

## Development

This project uses **uv** for package and environment management, **ruff** for linting and formatting, **ty** for type-checking, and **detect-secrets** for pre-commit secret scanning. All four are wired through `pre-commit`.

```bash
# Clone and install (Python 3.12+ required; uv will fetch if missing)
git clone https://github.com/kyleyhw/stemguessr.git
cd stemguessr
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Run hooks against all files
uv run pre-commit run --all-files
```

## Legal posture

- The repository contains **code only**. No audio is committed, ever.
- Users supply their own Spotify public playlist URL. No Spotify Premium account is required for ingestion (Client Credentials flow is sufficient for public playlist metadata).
- Audio is fetched at runtime from public preview endpoints (iTunes Search API; Deezer public API). These previews are not redistributed by this project; they are downloaded into a local on-disk cache for the user's own use.
- Users are responsible for compliance with the terms of the third-party APIs they query through this tool.

## License

To be added before public release.
