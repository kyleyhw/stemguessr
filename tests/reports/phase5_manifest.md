# Phase 5 Test Report — Manifest Builder

| Field | Value |
|-------|-------|
| Date | 2026-05-10 |
| Module under test | `stemguessr.manifest` |
| Test file | `tests/test_manifest.py` |
| Runner | pytest 9.0.3 on Python 3.12.12 (Windows 10 x64) |
| Result | **8 passed** |
| Total runtime | **0.43 s** |

## What was tested and why

The manifest builder is the contract surface between the Python ingest pipeline and the JavaScript frontend. The contract is a JSON file, so every field's name, type, encoding, and ordering matters for downstream code that has not yet been written. The test suite locks in:

1. **Every documented field appears with the correct type and shape**, so the frontend's reader can rely on the schema.
2. **Stem URLs are POSIX-relative regardless of host OS**, so a manifest built on Windows works unchanged on macOS / Linux.
3. **The track `id` falls back from ISRC to Spotify ID consistently**, so the frontend can use a single key without conditional logic.
4. **The two error paths fail with `ManifestError`** rather than letting partial / out-of-tree data corrupt the manifest.

### Happy-path manifest (2 tests)

- *All fields populated*. One track with full Spotify metadata and four stems. Asserts the top-level fields (`version`, `generated_at`, `model`, `stems`, `source_playlist`), the per-track fields (`id`, `spotify_id`, `isrc`, `title`, `artists`, `duration_ms`), and the ISO 8601 UTC timestamp format (suffix `+00:00`).
- *Stem paths are POSIX-relative URLs*. Verifies (a) the path layout `stems/{ID}/{stem}.wav` is correctly produced from absolute paths under `output_dir`, and (b) the resulting strings contain no backslashes — a Windows-specific gotcha if the conversion is not done explicitly.

### ID resolution (2 tests)

ISRC is the preferred stable key for cross-platform identity; the Spotify ID is only used when no ISRC is available. The two tests verify both branches independently.

### Error paths (2 tests)

- *Missing stem* — entry contains 1 of 4 expected stems → `ManifestError("missing stems: [...]")`. The CLI relies on this to surface programmer errors quickly during pipeline composition.
- *Stem path outside `output_dir`* — the WAV file is created in a sibling directory of `output_dir`. Verifies that `Path.resolve().relative_to()` raises and we wrap the `ValueError` as a `ManifestError` with a clear message.

### Ordering and edge cases (2 tests)

- *Track order preserved*. Three entries with distinct ISRCs are passed in a known order; the resulting `tracks` array preserves that order. Important because the playlist's playback order is the gameplay order (per `--shuffle` discussion deferred to Phase 6).
- *Empty playlist*. `entries=[]` → valid manifest with `"tracks": []`, version still `1`. Verifies the builder does not assume non-empty input.

## Failures

None.

## Reproduction

```bash
uv run pytest tests/test_manifest.py -v
```
