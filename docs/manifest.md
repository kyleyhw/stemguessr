# Manifest Schema

This document defines the `manifest.json` schema produced by [`src/stemguessr/manifest.py`](../src/stemguessr/manifest.py) — the **contract between the ingest pipeline and the static frontend**.

The frontend never touches the Spotify, iTunes, Deezer, or Demucs layers. It reads exactly two kinds of asset: this manifest, and the per-stem WAV files it references.

## Schema version

Current version: **1**.

The top-level `version` field is checked by the frontend on load. Future schema-breaking changes will bump this number; the frontend will refuse to render an unknown version rather than render incorrectly.

## Top-level shape

```json
{
  "version": 1,
  "generated_at": "2026-05-10T12:34:56+00:00",
  "source_playlist": {
    "spotify_id": "37i9dQZF1DXcBWIGoYBM5M",
    "url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
  },
  "model": "htdemucs",
  "stems": ["drums", "bass", "vocals", "other"],
  "tracks": [
    {
      "id": "USABC1234567",
      "spotify_id": "5fJG8X8sXJqVXjXYjQGk1z",
      "isrc": "USABC1234567",
      "title": "Example Song",
      "artists": ["Artist One", "Artist Two"],
      "duration_ms": 213_000,
      "stems": {
        "drums":  "stems/USABC1234567/drums.wav",
        "bass":   "stems/USABC1234567/bass.wav",
        "vocals": "stems/USABC1234567/vocals.wav",
        "other":  "stems/USABC1234567/other.wav"
      }
    }
  ]
}
```

## Field reference

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | Schema version. Always `1` at present. |
| `generated_at` | string | ISO 8601 timestamp with explicit UTC offset (`+00:00`). The build time of *this* manifest, not the playlist's creation time. |
| `source_playlist.spotify_id` | string | The 22-char Spotify playlist ID. |
| `source_playlist.url` | string | The original URL/URI the user supplied to the CLI. Preserved verbatim for traceability. |
| `model` | string | `"htdemucs"` or `"htdemucs_6s"`. The frontend uses this to label which stem set was used. |
| `stems` | array&lt;string&gt; | The stem names used for *all* tracks in this manifest, **in the order rounds should be revealed**. The frontend should not re-order. |
| `tracks` | array&lt;Track&gt; | Per-track entries; see below. Order matches the playlist's track order modulo skipped (preview-less) tracks. |

### Track entry

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | The stable identifier used as a key by the frontend. Equals `isrc` when available, else `spotify_id`. |
| `spotify_id` | string | Spotify track ID (always present). |
| `isrc` | string \| null | International Standard Recording Code. May be `null` if Spotify did not return one. |
| `title` | string | Track title, used as the answer the player must guess. |
| `artists` | array&lt;string&gt; | Artist names in Spotify's billing order. The first artist is typically the most useful for fuzzy answer matching. |
| `duration_ms` | int | Duration of the *original* track in milliseconds. The actual audio served via stems is the 30-second preview. |
| `stems` | object&lt;string, string&gt; | Map of stem name (matching the top-level `stems` array) to a POSIX-relative URL of the WAV file. |

## Why these specific fields

- **`id` derives from ISRC, falling back to Spotify ID.** ISRC is the international standard for recording identity (ISO 3901) and is portable across platforms; the Spotify ID is platform-specific. Using ISRC as the canonical key future-proofs the manifest against Spotify-side renames or catalogue replacements. Falling back to Spotify ID is necessary because a small fraction of tracks have no ISRC.
- **`title` and `artists` are kept verbatim.** Whatever fuzzy-matching the answer-checker performs in the frontend (case-folding, accent stripping, parenthetical removal) operates on these strings; the manifest does not pre-normalise them.
- **`duration_ms` refers to the full track**, even though the served audio is 30 s. This lets the UI show the *song's* real length on the answer-reveal screen without needing a separate field.
- **`stems` map is keyed by stem name, not array-indexed**, so the JSON survives a future stem-set change (e.g., 4 → 6 stems on an existing manifest) without re-indexing every consumer.

## Cache layout the manifest assumes

```
{cache_dir}/
├── previews/
│   └── {ISRC}.{m4a|mp3}      ← ingest input; not referenced by manifest
├── stems/
│   └── {ID}/
│       ├── drums.wav
│       ├── bass.wav
│       ├── vocals.wav
│       └── other.wav         ← referenced as "stems/{ID}/drums.wav" etc.
└── manifest.json
```

The frontend serves `cache_dir` as its static root, so the relative paths in the manifest are resolvable directly as URLs.

## Validation contract

The builder enforces two invariants:

1. **Every track entry must contain a path for every name in `stems`.** Partial separations are not representable; the CLI is responsible for excluding tracks that failed at any earlier stage.
2. **Every stem path must be located under `output_dir`.** The path is converted via `Path.resolve().relative_to(output_dir.resolve())` to a POSIX URL; an attempt to reference a file outside the cache root raises `ManifestError`.

Violations raise `ManifestError`; the CLI may catch and skip, or abort, at its discretion.

## Testing

Tests in [`tests/test_manifest.py`](../tests/test_manifest.py) cover:

- Full-fields happy path (4 stems, 1 track) — verifies all keys and value shapes.
- Path encoding — POSIX forward slashes regardless of host OS.
- ID resolution: ISRC when present; Spotify ID fallback.
- Error paths: missing stem; stem path outside `output_dir`.
- Multi-track ordering preservation.
- Empty playlist → valid manifest with `tracks: []`.

Run the tests:

```bash
uv run pytest tests/test_manifest.py -v
```

The latest test report is at [`../tests/reports/phase5_manifest.md`](../tests/reports/phase5_manifest.md).

## References

<span id="ref-iso-8601">[1]</span> ISO 8601-1:2019. *Date and time — Representations for information interchange.* International Organization for Standardization. [Link](https://www.iso.org/standard/70907.html)

<span id="ref-iso-3901">[2]</span> ISO 3901:2019. *Information and documentation — International Standard Recording Code (ISRC).* International Organization for Standardization. [Link](https://www.iso.org/standard/64817.html)
