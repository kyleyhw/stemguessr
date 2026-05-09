"""Demucs source separation wrapper.

Wraps :class:`demucs.api.Separator` to provide:

* model variant selection (``htdemucs`` default, ``htdemucs_6s`` opt-in)
* deterministic on-disk layout: ``output_dir/{stem_name}.wav``
* idempotency: when all expected outputs already exist, separation is skipped

Public API:

* :func:`separate` — high-level entry: input audio → cached stem WAVs.
* :data:`MODEL_STEMS` — tuple of stem names per model variant.
"""

from __future__ import annotations

from pathlib import Path

# Stem-name tuples per model variant. The 4-stem htdemucs splits the mixture
# into the four canonical sources of popular music; htdemucs_6s additionally
# separates guitar and piano from the residual "other" stem.
MODEL_STEMS: dict[str, tuple[str, ...]] = {
    "htdemucs": ("drums", "bass", "vocals", "other"),
    "htdemucs_6s": ("drums", "bass", "vocals", "other", "guitar", "piano"),
}


class SeparationError(RuntimeError):
    """Raised when separation cannot proceed (unknown model, etc.)."""


def _run_demucs(
    input_path: Path,
    output_dir: Path,
    model: str,
) -> dict[str, Path]:
    """Real Demucs invocation: load model, run inference, write per-stem WAVs.

    This function is the seam tests monkeypatch. Replacing it with a fake
    avoids the multi-hundred-megabyte model download on first run and the
    slow CPU inference path that would otherwise dominate the test suite.

    The torch / torchaudio / demucs imports are deferred to call time so
    that merely importing :mod:`stemguessr.separate` stays cheap.
    """
    import torchaudio  # ty: ignore[unresolved-import]
    from demucs.api import Separator  # ty: ignore[unresolved-import]

    separator = Separator(model=model)
    _, sources = separator.separate_audio_file(str(input_path))

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for stem_name, tensor in sources.items():
        out_path = output_dir / f"{stem_name}.wav"
        # torchaudio.save expects (channels, time); demucs returns the same.
        torchaudio.save(str(out_path), tensor.cpu(), separator.samplerate)
        paths[stem_name] = out_path
    return paths


def separate(
    input_path: Path,
    output_dir: Path,
    *,
    model: str = "htdemucs",
) -> dict[str, Path]:
    """Separate input audio into stems via Demucs, writing one WAV per stem.

    Idempotency: if all expected output WAVs already exist under ``output_dir``,
    the existing paths are returned immediately without invoking Demucs.
    Otherwise a full separation is performed and the WAVs are written.

    Args:
        input_path: Path to a readable audio file (any format
            torchaudio supports — typically MP3, M4A, WAV, FLAC).
        output_dir: Directory to write stem WAVs into; created if missing.
        model: ``"htdemucs"`` (4 stems) or ``"htdemucs_6s"`` (6 stems).

    Returns:
        Dict mapping stem name (e.g., ``"drums"``) to output WAV path.

    Raises:
        SeparationError: Unknown model name.
        FileNotFoundError: ``input_path`` does not exist on disk.
    """
    if model not in MODEL_STEMS:
        raise SeparationError(
            f"Unknown model {model!r}. Known models: {', '.join(MODEL_STEMS)}"
        )
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    expected_stems = MODEL_STEMS[model]
    expected_paths = {name: output_dir / f"{name}.wav" for name in expected_stems}

    if all(p.exists() for p in expected_paths.values()):
        return expected_paths

    return _run_demucs(input_path, output_dir, model)
