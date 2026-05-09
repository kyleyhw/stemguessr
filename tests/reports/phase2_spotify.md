# Phase 2 Test Report — Spotify Ingest Module

| Field | Value |
|-------|-------|
| Date | 2026-05-09 |
| Module under test | `stemguessr.spotify` |
| Test file | `tests/test_spotify.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **25 passed** |
| Total runtime | **0.83 s** |

## What was tested and why

The Spotify ingest module is responsible for translating a user-supplied playlist URL into a list of `Track` objects with ISRCs — the lookup key for downstream preview retrieval (Phase 3). The suite exercises all three public functions and explicitly stresses the resilience boundary (null tracks, missing ISRCs, partial credentials).

### `parse_playlist_id` — URL/URI parser

**Why tested.** Spotify exposes playlists in at least four URL forms (URI, web URL, web URL + share token, internationalised path); unrecognised forms must fail loudly rather than silently extracting garbage.

**Inputs chosen.**

- *Valid forms* (7 cases): every URL/URI shape observed in Spotify's outputs, plus a leading/trailing whitespace edge case. The chosen ID `37i9dQZF1DXcBWIGoYBM5M` is the public "Today's Top Hits" playlist — used purely for its valid-format properties; no API call is made.
- *Invalid forms* (10 cases): empty / whitespace-only input; non-URL strings; non-Spotify hosts; non-playlist Spotify URLs (album, track); URLs missing the ID; IDs of wrong length or charset (including a 22-char `!`-only string that exercises the regex without exercising the length guard).

**Coverage.** All branches: URI prefix match, host check, path component scan, missing-ID guard, format regex.

### `get_client` — credential resolution

**Why tested.** Credentials are sensitive; misconfigured environments must fail with a clear error rather than constructing a client that silently 401s on first request.

**Inputs chosen.**

- *Explicit args* override env. Constructs a real `spotipy.Spotify`; verified via `auth_manager is not None`.
- *Env-var fallback.* Set via `monkeypatch.setenv`; explicit args omitted.
- *Both missing.* Should raise `SpotifyError` with substring `"credentials not configured"`.
- *Only `SPOTIFY_CLIENT_ID` set.* Partial credentials are equivalent to missing.

The `monkeypatch` fixture isolates each test from the host environment so that a developer's real Spotify credentials cannot accidentally pass the suite.

### `fetch_playlist_tracks` — paginated extractor

**Why tested.** Real playlists routinely contain more than 100 tracks (Spotify's page cap), local files, removed tracks, and tracks without ISRCs. Each of these must be handled without aborting the ingest.

**Inputs chosen.**

- *Single-page response* (2 tracks, complete metadata). Verifies happy-path parsing into the `Track` dataclass and a single API call.
- *Two-page response* (1 track per page; `next` URL drives the second call). Verifies pagination loop and call count. Page size deliberately set to 1 to force pagination behaviour even with two synthetic tracks.
- *Mixed null entries:* explicit `track=None` (local file), a valid track, and `track.id=None` (malformed / removed). Verifies silent-skip semantics.
- *Track with `isrc=None`.* Verifies the field is preserved as `None` rather than coerced — the downstream layer (Phase 3) decides skip-vs-warn.

All client interactions go through a `MagicMock`; no network access is required.

## Failures

None.

## Reproduction

```bash
uv run pytest tests/test_spotify.py -v
```
