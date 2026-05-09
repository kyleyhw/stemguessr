# Phase 3 Test Report — Preview Source Lookup and Download

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Module under test | `stemguessr.sources` |
| Test file | `tests/test_sources.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **16 passed** |
| Total runtime | **0.51 s** |

## What was tested and why

The sources module is the layer between Spotify metadata and Demucs separation: given an ISRC, fetch and cache a 30-second preview, or report cleanly that none is available. The test suite exercises each public function, the internal retry helper, and the most important integration paths through `get_preview`.

All HTTP is faked via `httpx.MockTransport`, which routes every outbound request to a Python callable. This gives full control over response status, headers, and bodies without spinning up a local server. The autouse fixture `_no_real_sleeps` monkeypatches `stemguessr.sources.time.sleep` to a no-op so the retry-backoff paths execute in microseconds rather than seconds.

### `lookup_itunes` (4 tests)

**Why tested.** iTunes is the priority-1 source. The lookup must (i) return `PreviewMatch` correctly populated on hit, (ii) recognise both kinds of miss (empty `results` array; result present but missing `previewUrl`), (iii) raise `SourceError` rather than crashing on a non-JSON body.

**Inputs chosen.**

- *Hit*: `results` array with one element containing a `previewUrl`. The handler also asserts that the request URL hits `itunes.apple.com` and carries the correct `isrc` query parameter.
- *Miss, empty results*: `{"resultCount": 0, "results": []}` — the most common iTunes miss.
- *Miss, no previewUrl*: result present but lacks `previewUrl`. Edge case observed when iTunes has metadata but no streamable preview.
- *Non-JSON*: HTML body returned with 200 status. Should raise `SourceError`, not `JSONDecodeError`, so callers have a single exception type to handle.

### `lookup_deezer` (4 tests)

**Why tested.** Deezer signals misses inconsistently — sometimes 200 with an `error` object, sometimes 4xx — and we need to treat both as clean misses while still propagating server errors.

**Inputs chosen.**

- *Hit*: `{"id": ..., "preview": "..."}`. Handler asserts the URL contains the `isrc:{ISRC}` segment.
- *Miss via error object*: `{"error": {...}}` at HTTP 200.
- *Miss via 4xx*: HTTP 404; should be classified as a miss, not a hard error.
- *5xx propagates*: HTTP 503; should raise `httpx.HTTPStatusError` after retries, not silently miss.

### `_request_with_retry` (3 tests)

**Why tested.** Retry logic is easy to get subtly wrong: missing the final raise, retrying non-transient errors, miscounting attempts. These tests verify the policy under each branch.

**Inputs chosen.**

- *429-then-success*: first call returns 429 with `Retry-After: 0`; second returns 200. Verifies the 429 branch retries (and the call counter advances).
- *Network-error recovery*: first two calls raise `httpx.ConnectError`; third returns 200. Verifies exponential-backoff retries on transient network failures and that the success path is reached.
- *Exhaustion*: all calls raise `ConnectError`; verifies that after `max_retries=2` attempts the original exception is re-raised rather than swallowed.

### `get_preview` integration (5 tests)

**Why tested.** This is the public surface; the tests verify all four observable outcomes (cache hit, iTunes hit, Deezer fallback, both-miss) plus the atomicity invariant (no partial file leaked on download failure). All use `tmp_path` so each test runs in an isolated cache directory.

**Inputs chosen.**

- *Cache hit skips network*: a pre-existing `previews/{ISRC}.m4a` file is created by the test. The fake handler asserts that no network call is made — if `get_preview` ever calls out, the test fails loudly. Verifies the cache-hit short-circuit.
- *iTunes-first happy path*: handler routes iTunes lookups to a hit response and serves the audio when the previewUrl is fetched. Asserts the cached file's bytes match what the handler returned, and that the path ends in `.m4a`.
- *Deezer fallback*: iTunes returns empty results; Deezer returns a hit. Verifies fallback logic and that the cached extension is `.mp3`.
- *Both-miss → None*: both sources return their respective miss shapes. Verifies `None` is returned and that no `.m4a` or `.mp3` file is left in the cache.
- *Atomic write*: iTunes returns a previewUrl, but the audio download itself returns 503. Verifies no partial `.m4a` file leaks into the cache (only a `.tmp` may remain, and even that is acceptable to garbage-collect later).

## Failures

None.

## Reproduction

```bash
uv run pytest tests/test_sources.py -v
```
