# Phase 9 Test Report — Reset, Score Tracker, Distribution & Enter Key

| Field | Value |
|-------|-------|
| Date | 2026-07-09 |
| Scope | `stemguessr.server` (`/api/reset` cancel-then-clear, packaged frontend routing), `stemguessr.cli` (ingest cancellation), packaging (self-contained wheel), frontend (reset chip, score HUD, Enter key, favicon) |
| Test files | `tests/test_server.py` (new), `tests/test_cli.py` (cancellation tests + one assertion generalised), Playwright end-to-end sessions (game + reset-cancels-ingest harness) |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64); Playwright MCP (Chromium) |
| Result | **87 passed** (full suite minus `test_separate.py`); Playwright sessions: all checks passed |
| Total runtime | **4.26 s** (pytest); ~10 min wall-clock (interactive Playwright sessions) |

## Unit / integration tests (pytest)

### `tests/test_server.py` — 7 tests, why over real HTTP

The handler class is built by a closure (`_make_handler`) and served threaded; unit-testing methods in isolation would miss the routing, closure wiring, and threading. Each test therefore boots the production `_ThreadedHTTPServer` on an **ephemeral port** (bind to port 0 → OS assigns; no collisions in CI or parallel runs) against a `tmp_path` cache.

- **Reset clears the cache.** Cache seeded with one artefact of each kind reset must delete — `manifest.json`, a stem WAV, a preview file. This is the minimal set distinguishing "deleted the whole cache" from "deleted only one directory". Asserts HTTP 200 and that all three files *and* both directories are gone.
- **Reset is idempotent.** `POST /api/reset` on an empty cache returns 200, not an error — a double-click or premature reset must be harmless (`unlink(missing_ok=True)` + existence-guarded `rmtree`).
- **Reset cancels a running ingest.** A *real* thread models the pipeline's cooperative between-track cancellation by spinning on `state.should_cancel` (the production predicate, same lock and event). Reset asserts 200, that the fake observed the cancel and returned, that the state is no longer busy, and that every seeded file is deleted. This is the direct regression test for the reported bug ("reset does nothing while ingesting").
- **Reset times out gracefully if a run ignores cancellation.** With `_CANCEL_JOIN_TIMEOUT` monkeypatched to 0 and a thread that never observes the flag, reset returns 503 and leaves every seeded file intact — proving the join budget guards against deleting under a live writer.
- **Unknown POST → 404.** Route-fallthrough guard.
- **`GET /` serves the bundled frontend.** Asserts 200 and that the body contains "StemGuessr" — the regression guard for the `web/`-into-package move: if wheel bundling or `DEFAULT_WEB_DIR` resolution regresses, this fails first.
- **`GET /favicon.svg` serves the icon.** Asserts 200 and an `<svg` body, guarding both the route and the icon's inclusion in the wheel. Complements the browser check that the icon link suppresses the default `/favicon.ico` request.

### Packaging verification (manual, one-time)

`uv build --wheel` → wheel inspected with `zipfile`: `stemguessr/web/{index.html,styles.css,game.js}` present. `uv run --no-project --isolated --with dist/stemguessr-*.whl` → `DEFAULT_WEB_DIR` resolves inside the installed `site-packages` and all three assets exist. This proves `uvx stemguessr serve` works with no repo checkout.

### Adapted test

`test_version_flag_prints_version_and_exits` hard-coded the `0.1.` prefix and failed on the 0.2.0 bump (failure: `assert '0.1.' in 'stemguessr 0.2.0\n'`). Fixed by asserting `f"stemguessr {__version__}"` against the package's own version — the invariant under test is "the CLI prints its version", not the version's value.

## End-to-end verification (Playwright, scratch cache)

Run against a **copy** of `test_cache` (8 tracks, 4 stems) in the session scratchpad, so the destructive reset path could be exercised without touching a real cache. Server: `stemguessr serve --out <scratch> --port 8877 --no-browser`.

| Check | Result |
|-------|--------|
| Page load: prompt pre-filled from cached manifest; HUD shows `score 0/0` + `↺ reset`; main UI otherwise unchanged | ✓ |
| Score panel empty state on hover ("no completed tracks yet") | ✓ |
| Resume cached playlist → Track 1/8, Round 1/4; play starts (glyph ▶→■) | ✓ |
| Wrong guess advances round (1→2, drums→drums+bass), listed in guess log, score unchanged | ✓ |
| Correct guess ("Heartless", identified via fetched stem URLs) → reveal with cover, "solved on round 2 of 4", full-mix auto-play; score → 1/1 | ✓ |
| Four skips → miss recorded ("no win — out of guesses"); score → 1/2 | ✓ |
| Hover panel groups correctly: `stage 2 · 1 → Heartless`, `missed · 1 → Bound 2` | ✓ |
| Reset dialog **cancel** path: dialog wording correct; dismissing changes nothing (score, view, cache intact) | ✓ |
| Reset **accept** path (idle): client returns to empty prompt, score zeroed, URL field empty; scratch cache directory verified empty on disk | ✓ |
| Enter on reveal advances to next track (reveal hidden, Round 1/4, guess re-enabled) | ✓ |
| Enter with the *Next track* button focused advances **exactly once** (Track 2→3, not 4) — the `preventDefault` double-fire guard | ✓ |
| Enter submits guesses (all guesses in the session were submitted via Enter) | ✓ |
| Favicon: page requests `/favicon.svg` (200), never probes `/favicon.ico`; console fully clean (the former favicon 404 is gone) | ✓ |

### Reset cancels a *live* ingest (browser, via harness)

The reported bug is specifically about reset while an ingest is running. A real Demucs ingest is slow and network-dependent, so this was driven against the **real server** with the ingest pipeline swapped for a cooperative long-running fake (`scratchpad/cancel_harness.py`: monkeypatches `stemguessr.cli.run_ingest_pipeline` to write an in-progress manifest, then loop until `should_cancel`). The `/api/reset` code path — `cancel_and_join` then delete — is exactly the production one.

| Check | Result |
|-------|--------|
| Submitting a playlist starts the (fake) ingest; frontend leaves the prompt and shows "Waiting… · ingesting 0/5" with polling active — the state where the old code returned 409 | ✓ |
| Reset chip → confirm dialog shows the new wording ("cancels any ingest in progress…") | ✓ |
| Accepting: request returns promptly (not the 60 s timeout), frontend returns to the empty prompt, reset button re-enabled | ✓ |
| Cache directory verified empty on disk — the fake's manifest was deleted, proving cancel→join→delete completed (a non-cancelled thread would have forced 503 with the cache intact) | ✓ |
| A subsequent idle `POST /api/reset` still returns 200 (server not wedged) | ✓ |

## Launcher / uninstaller scripts

`run.command` and `uninstall.command` are verified statically (no macOS runner available in this environment): `git show :run.command | file -` reports "Bourne-Again shell script, ASCII text executable" with zero carriage returns, confirming the `.gitattributes` LF pinning holds in the committed blob (a CRLF here would break the shebang on macOS). Both `.command` files are staged mode `100755`, so GitHub's ZIP export and macOS Archive Utility preserve the executable bit that lets Finder run them. Runtime behaviour on macOS (double-click → Terminal, Gatekeeper one-time approval) is documented in `docs/distribution.md` rather than asserted here.

## Failures

One pytest failure during the phase (the hard-coded version assertion, documented above); fixed and re-run to green. No end-to-end failures. The previously out-of-scope favicon 404 is now fixed and covered (route test + browser check).

## Reproduction

```bash
uv run pytest --ignore=tests/test_separate.py -q   # 87 passed
uv run pytest tests/test_server.py tests/test_cli.py -v   # reset/cancel + routing detail
```
