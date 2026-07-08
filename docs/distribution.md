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

The install is symmetric across the two OSes: **one download, one double-click.** Download the repo ZIP from GitHub ([Code → Download ZIP](https://github.com/kyleyhw/stemguessr/archive/refs/heads/main.zip)), unzip it, and double-click the launcher for the OS:

| OS | Double-click | First-run security prompt |
|----|-------------|---------------------------|
| **Windows** | `run.bat` | SmartScreen may show "Windows protected your PC" → *More info* → *Run anyway*. One-time. |
| **macOS** | `run.command` | Gatekeeper may say the file is from an unidentified developer → **Control-click `run.command` → Open → Open**. One-time. |

Each launcher installs `uv` if it is missing, then starts the server; the game opens in the browser automatically. The two scripts are byte-for-byte parallel — same three steps (find/install `uv`, `uv run --no-dev stemguessr serve`, keep the window open on error) — differing only in shell.

The first-run security prompt is the one asymmetry I cannot remove: both OSes flag files downloaded from the internet, and clearing that flag for good requires code-signing certificates (a paid Apple Developer ID on macOS; an EV cert on Windows). Both prompts are one-time per download and take one extra click. `run.command` ships with its executable bit set in git (mode `100755`), which GitHub's ZIP export and macOS's Archive Utility both preserve, so Finder treats it as a program rather than opening it in a text editor.

**Terminal alternative (either OS), once the package is on PyPI:** install `uv` with its one-line script ([Windows](https://docs.astral.sh/uv/getting-started/installation/): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`; macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`), then `uvx stemguessr serve`.

The server opens the game in the default browser as soon as its socket is bound (`--no-browser` disables this). The browser-open call is made immediately after binding rather than after a delay: a TCP connection arriving before `serve_forever()` starts simply queues in the listen backlog and is served milliseconds later, so no port-polling loop is needed anywhere.

**First-run cost (any route, any OS):** ~2–3 GB of Python dependencies (dominated by PyTorch) plus ~250 MB of Demucs model weights, downloaded once into `uv`'s cache and the Demucs cache respectively. Subsequent launches start in seconds. This cost is inherent to constraint 1 — local separation means a local PyTorch.

## Uninstalling

Symmetric with install: double-click `uninstall.bat` (Windows) or `uninstall.command` (macOS). Each removes StemGuessr's footprint in two tiers:

1. **App-local, always removed:** the project virtual environment (`.venv`) and the ingested cache (`cache/`, holding stems and previews). These sit inside the downloaded folder, so deleting the folder would also remove them — the script does it explicitly so the disk is reclaimed before you delete anything.
2. **Shared downloads, removed only on confirmation:** `uv`'s package cache and the Demucs model weights (`~/.cache/torch`), together the ~2–3 GB bulk. These live *outside* the folder and may be shared with other `uv`/PyTorch projects, so the script asks first and defaults to *no*. On a machine used only for StemGuessr, answering yes reclaims essentially everything.

The scripts deliberately leave `uv` itself installed (it is a general-purpose tool the friend may want) and print the one-liner to remove it — `uv self uninstall` — for a total wipe. After running the uninstaller, deleting the StemGuessr folder finishes the job.

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
