# StemGuessr

A music-guessing game built around source-separated stems. Given any *public* Spotify playlist URL, the ingest pipeline parses Spotify's own embed page for the playlist (no auth required), downloads each track's 30-second preview from Spotify's CDN, separates the clip into instrument stems with Demucs, and serves the stems to a static browser frontend that reveals one stem per round of guessing.

## Quickstart

> **Requirements** — Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) on `PATH`. No Spotify credentials.

**1. Install.**

```bash
git clone https://github.com/kyleyhw/stemguessr.git
cd stemguessr
uv sync
```

**2. Run the server.**

```bash
uv run stemguessr serve --out ./cache
```

**3. Open <http://localhost:8765/>**, paste a public Spotify playlist URL into the form, and play.

The first invocation downloads ~250 MB of Demucs weights, after which each track separates in ~5–15 s on CPU and becomes playable the moment it finishes. Re-running against the same playlist is a cache hit (no network, no Demucs).

For non-interactive use, `stemguessr ingest <url> [--out PATH] [--stems {4,6}] [--limit N] [--force-refresh]` runs the same pipeline without the server — see [`docs/cli.md`](docs/cli.md).

## Status

**v0.1.3 — 2026-05-10.** `stemguessr serve` runs the whole thing in one command: open the page, paste a Spotify playlist URL, play. Progressive ingest streams tracks in as Demucs separates them; album cover on reveal; clickable + draggable waveform scrub; volume slider; no Spotify credentials required. See [`CHANGELOG.md`](CHANGELOG.md) for the release log and [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the phased build log.

## System architecture

The pipeline has three stages: two off-line and one in the browser.

1. **Spotify embed parsing** (off-line, no auth). Fetch `https://open.spotify.com/embed/playlist/<id>`, extract the `__NEXT_DATA__` JSON the Next.js page embeds for its React client. Each track in that JSON carries title, artist names, duration, and a direct 30-second MP3 preview URL on Spotify's CDN. The CDN URL is downloaded into the on-disk cache.
2. **Demucs source separation** (off-line, on-disk cache). Each cached preview is split into stems — by default `{drums, bass, vocals, other}` using `htdemucs`, optionally six stems via `htdemucs_6s` which adds `{guitar, piano}`. Outputs are WAV per stem under `stems/<spotify_id>/`.
3. **Static frontend** (browser). A single `index.html` fetches `manifest.json` and plays stems through Web Audio `AudioBufferSourceNode`s, summed through a master `GainNode` for volume control. The game reveals one stem per round; the player has four guesses (six in 6-stem mode).

```mermaid
flowchart TD
    A[Public Spotify playlist URL]
    B["open.spotify.com/embed/playlist/&lt;id&gt;<br/>parse __NEXT_DATA__ JSON"]
    C["Tracks with title, artists,<br/>duration, preview_url"]
    D["Disk cache:<br/>previews/&lt;spotify_id&gt;.mp3"]
    E["Demucs htdemucs<br/>4-stem (or htdemucs_6s, 6-stem)"]
    F["stems/&lt;spotify_id&gt;/{drums,bass,vocals,other}.wav"]
    G["manifest.json"]
    H["Static browser game<br/>(Web Audio + Canvas)"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
```

## Source separation, briefly

Source separation is the inverse problem: given a mixture
$x(t) = \sum_{i=1}^{N} s_i(t)$, recover each source $s_i(t)$ for $i \in \{1, \dots, N\}$ where $N$ is the number of stems (4 or 6 here). The current state-of-the-art family — Hybrid Demucs (`htdemucs`) — is a U-Net with two parallel branches that exchange features at multiple depths:

- A **time-domain** 1-D convolutional branch that operates directly on the waveform $x(t)$.
- A **spectrogram-domain** 2-D branch that operates on the complex STFT $X(t, f) = \mathrm{STFT}\{x\}(t, f)$ and predicts complex-valued masks $M_i(t, f)$ for each source.

The two branch outputs are summed in the time domain to give the final source estimates $\hat{s}_i(t)$. The hybrid design is motivated by the empirical observation that some sources (drums, transients) are better separated in the time domain, while others (sustained tones, harmonic content) are better separated in the spectrogram domain.

A full derivation — training objective (L1 + multi-resolution STFT), complex-mask parameterisation, the HT transformer extension, and the choice of `htdemucs` over baseline Demucs — is in [`docs/separation.md`](docs/separation.md).

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

