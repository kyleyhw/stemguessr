# Phase 4 Test Report — Demucs Separation Wrapper

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Module under test | `stemguessr.separate` |
| Test file | `tests/test_separate.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **8 passed** |
| Total runtime | **0.07 s** |

## What was tested and why

The separation wrapper is the seam between the cached audio preview (Phase 3) and the manifest builder (Phase 5). It is intentionally thin — most of its complexity is in the Demucs library underneath — but the wrapper itself enforces three invariants that are easy to break and not covered by Demucs's own tests: stem-catalogue agreement, idempotency, and graceful failure on bad inputs.

The real `_run_demucs` invokes `torch` and `demucs.api.Separator`, downloads ~250 MB of model weights on first call, and runs CPU inference for several seconds per track. Tests therefore monkeypatch `_run_demucs` with `_fake_run_demucs`, which writes 44-byte WAV-header-shaped placeholders for each expected stem. The suite runs in 0.07 s and is fully offline — Demucs's own correctness is verified by Demucs's own test suite, not here.

A genuine end-to-end Demucs run is deferred to **Phase 8** (Integration & Polish), behind an opt-in environment variable.

### `MODEL_STEMS` (2 tests)

**Why tested.** `MODEL_STEMS` is a public constant; downstream code (manifest builder, frontend, CLI) imports it as the source of truth for what stems to expect per model. A silent change here would corrupt the manifest schema without crashing.

**Inputs chosen.** Direct equality assertions against the documented tuples for both model variants.

### `separate` — error paths (2 tests)

- *Unknown model* → `SeparationError`. We check the message contains `"Unknown model"` so users get an actionable error rather than a downstream `KeyError`.
- *Missing input file* → `FileNotFoundError`. Caught at wrapper level rather than letting Demucs fail with a less-clear error.

### `separate` — happy path with mocked Demucs (1 test)

- 4-stem run from scratch. Output dir is empty; after the call, all four expected WAVs exist on disk; the returned dict maps each stem name to the corresponding path. Verifies the contract Demucs callers rely on.

### `separate` — idempotency (2 tests)

- *All outputs already exist.* The fake `_run_demucs` is replaced with a sentinel (`_must_not_call`) that fails the test if invoked. The wrapper must short-circuit and return the existing paths without ever touching the separator. This is the load-bearing test — re-running ingest on a cached playlist is essentially free, and that property is what makes the cache useful.
- *Partial outputs.* Only `drums.wav` is pre-created; the wrapper must invoke `_run_demucs` (verified via a mutable flag) to produce the missing stems. Demucs does not support partial separation, so a re-run from scratch is the only correct behaviour.

### `separate` — 6-stem mode (1 test)

- `model="htdemucs_6s"` produces a dict of 6 paths, including `guitar` and `piano`. Verifies the model parameter is plumbed all the way through.

## Failures

None.

## Reproduction

```bash
uv run pytest tests/test_separate.py -v
```
