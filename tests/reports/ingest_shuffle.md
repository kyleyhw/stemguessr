# Test Report — Shuffled Ingest Order

| Field | Value |
|-------|-------|
| Date | 2026-07-07 |
| Module under test | `stemguessr.cli` (`run_ingest_pipeline` processing order) |
| Test file | `tests/test_cli.py` (`TestShuffledOrder`, plus one adapted happy-path test) |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **11 passed** (full `test_cli.py`); **78 passed** (all non-Demucs suites) |
| Total runtime | **0.45 s** (`test_cli.py` alone); **0.70 s** (all non-Demucs suites) |

## What was tested and why

The ingest pipeline previously processed tracks in playlist order. Because the manifest is written progressively (one rewrite per separated track) and the frontend appends newly arrived tracks in arrival order — its own Fisher–Yates shuffle covers only the tracks present at its *first* manifest fetch, typically a single track during a live ingest — ingestion order was the effective play order, and the first playable track was always the playlist's first track. The fix shuffles the track list (after the `--limit` slice, on a copy) before the ingest loop. These tests pin down that behaviour.

### Processing order follows the shuffle (1 test)

`random.shuffle` is replaced via `monkeypatch` with a deterministic in-place reversal (`seq.reverse()`), which has the same call signature and in-place mutation contract. The pipeline is then run over five stub tracks `id0..id4`, and the sequence of `download_preview` cache keys is asserted to be exactly `id4..id0`.

**Why this design:** asserting on the output of the real `random.shuffle` would require either a fixed seed (fragile — CPython does not guarantee `shuffle` reproducibility across versions) or a statistical test (slow, flaky). Substituting a deterministic permutation instead proves the load-bearing property directly: the pipeline's processing order is whatever the shuffle produces, not playlist order.

**Why five tracks:** a reversal of a 0- or 1-element list is the identity, and with 2 elements a reversal could coincide with other off-by-one errors; five distinct IDs make the reversed order unambiguous.

### Source list is not mutated (1 test)

`fetch_playlist_tracks`'s returned list (aliased by the test stub) is asserted to be element-wise unchanged after the run. This pins the "shuffle a copy" implementation detail: `random.shuffle` is in-place, and when `--limit` is absent the pipeline would otherwise shuffle the caller-visible list. `Track` is a frozen dataclass, so element-wise `==` is well-defined.

### Adapted test: download calls compared as sets

`test_download_called_with_track_preview_url` previously asserted `download_calls[i]` against `tracks[i]` positionally — an ordering guarantee the shuffle intentionally removes. It now compares `{(preview_url, spotify_id)}` sets, which preserves the property actually under test (each track's preview URL is passed through, keyed by its Spotify ID) without asserting an order.

## Failures

The positional `test_download_called_with_track_preview_url` was identified ahead of the change as incompatible with shuffled ordering (it would fail intermittently, whenever the 2-element shuffle produced the swapped order). It was converted to the order-independent set comparison described above before the final run; all 78 tests then passed on the first run.

## Reproduction

```bash
uv run pytest tests/test_cli.py -v
uv run pytest tests/test_cli.py tests/test_manifest.py tests/test_spotify.py tests/test_sources.py tests/test_fixture_manifest.py
```
