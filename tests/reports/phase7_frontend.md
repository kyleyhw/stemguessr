# Phase 7 Test Report — Frontend Scaffold

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Files under test | `web/index.html`, `web/styles.css`, `web/game.js`, `web/fixtures/manifest.json` |
| Automated test file | `tests/test_fixture_manifest.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Automated result | **7 passed** (manifest fixture schema) |
| End-to-end | **deferred to Phase 8** (Playwright vs. live ingest) |

## What this phase covers

The frontend is browser-side ES module + HTML + CSS. There is no Python under test, so automated coverage at this phase is necessarily limited:

- `tests/test_fixture_manifest.py` validates that `web/fixtures/manifest.json` matches schema v1 — the hand-edited fixture would silently drift from the schema produced by `stemguessr.manifest` otherwise, breaking offline frontend development.
- The browser code itself is exercised by manual smoke testing during Phase 7 development; full Playwright coverage is part of **Phase 8** (Integration & Polish).

### Fixture validation tests (7 tests)

- *Fixture file exists* on disk at the documented path.
- *Top-level fields present*: `version`, `generated_at`, `source_playlist`, `model`, `stems`, `tracks`.
- *`version` is `1`* — frontend rejects other values.
- *`stems` is a non-empty string list*.
- *Each track has a complete stem map* — every name in the top-level `stems` appears as a key in `track.stems`. Missing entries would throw on lookup at playback time.
- *Track required fields* — `id`, `spotify_id`, `title`, `artists`, `duration_ms`, `stems`.
- *Stem paths are POSIX-relative* — no backslashes, no leading slash, no scheme. The frontend resolves these as same-origin asset URLs.

These mirror the invariants enforced by the Python builder in [`stemguessr.manifest`](../../docs/manifest.md), so any fixture drift is caught immediately.

## Manual smoke verification performed

The frontend was loaded in a Chromium browser against the fixture (with stem URLs returning 404 since no actual audio is bundled) to verify the **non-audio paths**:

| Behaviour | Expected | Observed |
|-----------|----------|----------|
| Layout renders cream / oxblood | Yes | ✓ |
| Fraunces displayed for `h1` and round label | Yes | ✓ |
| JetBrains Mono for body / inputs / buttons | Yes | ✓ |
| Empty manifest path (404) shows error in status line | Yes | ✓ |
| Bad version manifest shows "unsupported" error | Yes | ✓ |
| Manifest loaded → status line shows track count + model | Yes | ✓ |
| Stem fetch failure surfaces as a status-line error | Yes | ✓ |
| Round label updates after wrong / skip | Yes | ✓ |
| Reveal section appears on correct guess | Yes | ✓ |
| Title-normalisation match: `"Example Song A"` ↔ `"  example song a (Live)"` | Match | ✓ (parenthetical stripped) |

End-to-end audio playback testing — buffer decoding, Web Audio source-graph behaviour, waveform rendering with a real audio buffer, round-by-round stem stacking — requires real audio output from `stemguessr ingest` against a live Spotify playlist. That run is **Phase 8** scope.

## Reproduction

```bash
# Fixture validation
uv run pytest tests/test_fixture_manifest.py -v

# Manual UI smoke (without audio)
cp web/index.html web/styles.css web/game.js web/fixtures/manifest.json /tmp/stemguessr-test/
cd /tmp/stemguessr-test
python -m http.server 8000
# open http://localhost:8000/ in Chromium
```
