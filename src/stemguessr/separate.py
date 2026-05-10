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

# Stem-name tuples per model variant, in **game-reveal order**. The 4-stem
# htdemucs splits the mixture into the four canonical sources of popular
# music; htdemucs_6s additionally separates guitar and piano from the
# residual "other" stem.
#
# Vocals are placed last because the lyrics + identifiable singer make them
# the easiest stem to identify a song from; revealing them first would
# trivialise the guessing loop. The ordering progresses from rhythm-only
# (drums, bass) through harmonic content (other; plus guitar and piano in
# the 6-stem variant) to vocals.
MODEL_STEMS: dict[str, tuple[str, ...]] = {
    "htdemucs": ("drums", "bass", "other", "vocals"),
    "htdemucs_6s": ("drums", "bass", "other", "guitar", "piano", "vocals"),
}


class SeparationError(RuntimeError):
    """Raised when separation cannot proceed (unknown model, etc.)."""


def _run_demucs(
    input_path: Path,
    output_dir: Path,
    model: str,
) -> dict[str, Path]:
    """Real Demucs invocation: load pretrained model, apply it to the audio,
    write per-stem WAVs.

    Uses Demucs's lower-level API (``apply_model`` + ``get_model``) rather
    than the higher-level ``demucs.api.Separator`` which is only present in
    Demucs 4.1+. This works back to Demucs 4.0.

    This function is the seam tests monkeypatch — replacing it avoids the
    multi-hundred-megabyte model download on first run and the slow CPU
    inference path that would otherwise dominate the test suite.

    The torch / torchaudio / demucs imports are deferred to call time so
    that merely importing :mod:`stemguessr.separate` stays cheap.
    """
    import soundfile as sf  # ty: ignore[unresolved-import]
    import torch  # ty: ignore[unresolved-import]
    import torchaudio  # ty: ignore[unresolved-import]
    from demucs.apply import apply_model  # ty: ignore[unresolved-import]
    from demucs.pretrained import get_model  # ty: ignore[unresolved-import]

    pretrained = get_model(model)
    pretrained.eval()

    # Load via soundfile (libsndfile-backed; supports MP3/M4A/WAV without
    # requiring FFmpeg). soundfile returns (frames, channels) float32.
    audio, sample_rate = sf.read(str(input_path), dtype="float32", always_2d=True)
    # → torch tensor of shape (channels, frames).
    waveform = torch.from_numpy(audio.T).contiguous()

    if sample_rate != pretrained.samplerate:
        waveform = torchaudio.functional.resample(
            waveform, sample_rate, pretrained.samplerate
        )
    # Demucs expects stereo; duplicate mono if necessary.
    if waveform.shape[0] == 1 and pretrained.audio_channels == 2:
        waveform = waveform.repeat(2, 1)

    # apply_model wants (batch, channels, time).
    with torch.no_grad():
        sources = apply_model(
            pretrained,
            waveform[None],
            shifts=1,
            split=True,
            overlap=0.25,
            progress=False,
        )[0]
    # `sources` is (n_sources, channels, time); `pretrained.sources` is the
    # ordered list of stem names.

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for stem_name, tensor in zip(pretrained.sources, sources, strict=True):
        out_path = output_dir / f"{stem_name}.wav"
        # soundfile.write expects (frames, channels) float; tensor is
        # (channels, frames). Transpose and convert.
        sf.write(str(out_path), tensor.cpu().numpy().T, pretrained.samplerate)
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
