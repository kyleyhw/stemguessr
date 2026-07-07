# Distribution

How StemGuessr gets onto a machine that has no Python toolchain installed — a friend's Windows or macOS computer — while keeping *all* processing (ingest, Demucs separation, playback) local to that machine.

## Design constraints

1. **Everything local.** The game server, the Spotify embed fetch, the preview downloads, and the Demucs separation all run on the player's machine. No cloud service, no shared server.
2. **No pre-installed toolchain.** The target machine has neither Python nor `uv`.
3. **Cross-platform.** Windows and macOS, without maintaining per-OS builds.

## Why the alternatives were rejected

**Static hosting (GitHub Pages).** Pages serves files only — there is no process to run Demucs. Even if separation were ported to the browser (Demucs *has* been compiled to WebAssembly elsewhere, at major engineering cost), the browser cannot fetch the Spotify embed page or the preview MP3s cross-origin: those hosts send no CORS headers, so the requests are blocked before they leave the page. Working around that requires a CORS proxy — a server — which violates constraint 1. The Python server exists precisely to do those fetches.

**Standalone executables (PyInstaller).** Requires one build per OS (and per macOS architecture), each ~2–3 GB because PyTorch must be bundled. Unsigned binaries trip Windows SmartScreen and are blocked outright by macOS Gatekeeper without a paid Apple developer signature. Every release would need a rebuild. Rejected as the highest-maintenance option.

**Chosen: a self-contained wheel + `uv`.** `uv` installs with a one-line script on both OSes, provisions a managed Python automatically, and `uvx stemguessr serve` resolves, installs, and runs the published wheel in one command [[1]](#ref-uv). The wheel is self-contained: the frontend (`index.html`, `styles.css`, `game.js`) ships inside the package at `src/stemguessr/web/`, resolved at runtime as `Path(__file__).parent / "web"` — wheels are always installed as real directories, so no `importlib.resources` indirection is needed.

## What a friend actually does

| OS | Steps |
|----|-------|
| **Windows** | Download the repo ZIP from GitHub → unzip → double-click `run.bat`. It installs `uv` if missing, starts the server, and the game opens in the browser automatically. |
| **Windows (terminal)** | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`, then `uvx stemguessr serve` in a new terminal. |
| **macOS** | Paste into Terminal: `curl -LsSf https://astral.sh/uv/install.sh \| sh` , then `uvx stemguessr serve` in a new terminal (or `~/.local/bin/uvx stemguessr serve` in the same one). |

The server opens the game in the default browser as soon as its socket is bound (`--no-browser` disables this). The browser-open call is made immediately after binding rather than after a delay: a TCP connection arriving before `serve_forever()` starts simply queues in the listen backlog and is served milliseconds later, so no port-polling loop is needed anywhere.

**First-run cost (any route, any OS):** ~2–3 GB of Python dependencies (dominated by PyTorch) plus ~250 MB of Demucs model weights, downloaded once into `uv`'s cache and the Demucs cache respectively. Subsequent launches start in seconds. This cost is inherent to constraint 1 — local separation means a local PyTorch.

## Publishing to PyPI

Releases publish via GitHub Actions **trusted publishing** (OIDC): PyPI trusts release builds from this specific repository and workflow, so no long-lived API token is stored in repo secrets [[2]](#ref-trusted-publishing). The workflow is [`.github/workflows/publish.yml`](../.github/workflows/publish.yml); it triggers on every published GitHub release, builds the sdist and wheel with `uv build`, and uploads with `uv publish`.

### One-time setup (repository owner, manual)

1. Create a PyPI account and, under *Publishing → Add a new pending publisher*, register:
   - PyPI project name: `stemguessr`
   - Owner: `kyleyhw`, repository: `stemguessr`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
2. In the GitHub repo settings, create an environment named `pypi` (Settings → Environments). No secrets are needed in it; it exists so the trusted-publisher binding is scoped to release runs.

### Per-release procedure

1. Bump `version` in `pyproject.toml`; update `CHANGELOG.md`.
2. Commit, push, and create a GitHub release (tag `vX.Y.Z`). The workflow builds and publishes automatically.

Until the first PyPI publish exists, the git-based form works for anyone with `git` installed: `uvx --from git+https://github.com/kyleyhw/stemguessr stemguessr serve`.

## References

<span id="ref-uv">[1]</span> Astral. *uv — An extremely fast Python package and project manager.* [Link](https://docs.astral.sh/uv/)

<span id="ref-trusted-publishing">[2]</span> Python Packaging Authority. *Publishing to PyPI with a Trusted Publisher.* [Link](https://docs.pypi.org/trusted-publishers/)
