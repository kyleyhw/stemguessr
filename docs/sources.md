# Preview Source Lookup and Download

This document describes [`src/stemguessr/sources.py`](../src/stemguessr/sources.py): the layer that takes an ISRC and returns a path to a cached 30-second audio preview, or signals that no source has it.

## Why a separate layer

Spotify itself does not expose raw audio. Stems cannot be cut from data Spotify never gives us. The pipeline therefore introduces an *audio-source* layer between Spotify (metadata) and Demucs (stem separation): given an ISRC, fetch a public 30-second preview from a provider that does serve audio, cache it locally, and pass the file path forward.

## Source priority

Sources are queried in fixed priority order, with the first hit wins:

| Priority | Source | Endpoint | Format | Notes |
|----------|--------|----------|--------|-------|
| 1 | iTunes Search API | `https://itunes.apple.com/lookup?isrc={ISRC}&entity=song` | 30 s AAC in M4A container | Public, no auth, very stable. Apple actively promotes preview use in third-party apps. |
| 2 | Deezer Public API | `https://api.deezer.com/track/isrc:{ISRC}` | 30 s 128 kbps MP3 | Public, no auth. Used as fallback because Deezer's TOS is more restrictive. |

**Why iTunes first.** Apple's Search API has been stable for ~15 years and explicitly permits third-party app integration of preview clips. Deezer's TOS is more guarded and the public API has had episodes of tightening. Putting iTunes first minimises the share of traffic that hits Deezer.

**Combined coverage.** Empirically, the union of iTunes + Deezer covers essentially every track on Spotify with an ISRC. Misses, when they happen, are typically:

- Tracks newly released and not yet indexed by either service.
- Region-restricted / pulled tracks.
- Spotify entries lacking an ISRC altogether (already filtered out at the Spotify layer if `isrc=None`).

## Cache layout

```
{cache_dir}/
└── previews/
    ├── USABC1234567.m4a   ← from iTunes
    ├── DEABC2345678.mp3   ← from Deezer
    └── ...
```

The file extension encodes the source: `.m4a` came from iTunes (AAC), `.mp3` came from Deezer. There is no separate manifest file at this layer; cache lookup is purely by ISRC stem and extension probing.

The cache is *content-addressed by ISRC*: the same ISRC always maps to the same filename, regardless of how many times ingest is run. This makes the cache idempotent — re-running ingest on the same playlist is essentially free after the first run.

## Atomic writes

Downloads use a temp-file + rename pattern (`Path.replace`), so a download interrupted mid-write never leaves a half-complete file at the canonical path. A worst-case interruption leaves an orphan `*.tmp` file, which the next ingest will simply overwrite.

## Retry policy

Implemented in `_request_with_retry`. The default policy is **3 attempts**, with **exponential backoff** of 1, 2, 4 seconds between attempts. Specifically:

- **HTTP 429 (Too Many Requests).** Honour the `Retry-After` header if present, otherwise back off by `2**attempt`. Capped at 30 seconds per individual sleep so a misbehaving server cannot stall ingest indefinitely.
- **Network errors** (`httpx.RequestError`) **and 5xx**. Back off by `2**attempt`, retry. After the final attempt, the exception is re-raised.
- **4xx other than 429.** Not retried. Treated as a clean miss for Deezer (it returns 4xx for unknown ISRCs); raised as an `httpx.HTTPStatusError` for iTunes. iTunes does not normally 4xx for unknown ISRCs — it returns `200 {"results": []}`.

The mathematical bound on time-to-failure with retries exhausted is

$$
T_{\text{worst}} = \sum_{k=0}^{R-2} \min(2^k, 30) = 1 + 2 + 4 + \ldots = 2^{R-1} - 1 \quad \text{seconds},
$$

where $R$ is `max_retries`. For the default $R=3$, $T_{\text{worst}} = 3$ s of sleep before the final attempt's network timeout.

## Failure model

`get_preview(isrc, cache_dir)` returns:

- `Path` on success (file is on disk and readable).
- `None` on a clean miss from all sources.

It raises only when something has gone *wrong* (5xx that survived retries, malformed JSON from a source). This separation matters: a miss is a normal outcome that the caller may want to log and move on; an exception means the network or a service is broken and the caller should likely abort the run.

## Testing

Tests in [`tests/test_sources.py`](../tests/test_sources.py) use httpx's `MockTransport` to fake every HTTP request. `time.sleep` is monkeypatched to a no-op so retry paths run instantly.

Coverage:

- iTunes hit / empty-results miss / no-`previewUrl` miss / non-JSON error.
- Deezer hit / `error`-object miss / 4xx miss / 5xx propagation.
- Retry helper: 429-then-success; network-error recovery; exhaustion → re-raise.
- `get_preview` end-to-end: cache hit (network must not be called); iTunes-first happy path; Deezer fallback after iTunes miss; both-miss returning None; no leaked partial file on download failure.

Run the tests:

```bash
uv run pytest tests/test_sources.py -v
```

The latest test report is at [`../tests/reports/phase3_sources.md`](../tests/reports/phase3_sources.md).

## References

<span id="ref-itunes-search">[1]</span> Apple. *iTunes Search API.* [Link](https://performance-partners.apple.com/search-api)

<span id="ref-deezer-api">[2]</span> Deezer. *API documentation: track lookup by ISRC.* [Link](https://developers.deezer.com/api/track)

<span id="ref-rfc6585">[3]</span> Nottingham, M., & Fielding, R. (2012). *Additional HTTP Status Codes* (RFC 6585), §4 (429 Too Many Requests). [Link](https://datatracker.ietf.org/doc/html/rfc6585)
