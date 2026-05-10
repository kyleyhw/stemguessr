"""Tests for stemguessr.separate module.

The real :func:`stemguessr.separate._run_demucs` invokes torch + demucs and
downloads multi-hundred-MB model weights on first use. Tests monkeypatch it
with a fake that writes minimal valid WAV-shaped bytes per stem, so the suite
runs in milliseconds and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stemguessr.separate import (
    MODEL_STEMS,
    SeparationError,
    separate,
)


def _fake_run_demucs(input_path: Path, output_dir: Path, model: str) -> dict[str, Path]:
    """Stand-in for the real Demucs call: writes 44-byte placeholder per stem."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for stem in MODEL_STEMS[model]:
        p = output_dir / f"{stem}.wav"
        # 44 bytes is the minimum valid WAV header size; opaque to these tests
        # which never actually decode the audio.
        p.write_bytes(b"\x00" * 44)
        paths[stem] = p
    return paths


class TestModelStems:
    """Sanity-check the stem catalogue against external expectations."""

    def test_htdemucs_4_stems(self) -> None:
        # Game-reveal order: vocals last so the lyrics aren't the first
        # thing the player hears.
        assert MODEL_STEMS["htdemucs"] == ("drums", "bass", "other", "vocals")

    def test_htdemucs_6s_extends_to_guitar_piano(self) -> None:
        # Same vocals-last principle; harmonic content (other, guitar, piano)
        # sits between rhythm and vocals.
        assert MODEL_STEMS["htdemucs_6s"] == (
            "drums",
            "bass",
            "other",
            "guitar",
            "piano",
            "vocals",
        )

    def test_vocals_is_always_last(self) -> None:
        for model, stems in MODEL_STEMS.items():
            assert stems[-1] == "vocals", (
                f"model {model!r} must put vocals last (got {stems[-1]!r})"
            )


class TestSeparate:
    """End-to-end behaviour of :func:`separate` with the Demucs call faked."""

    def test_unknown_model_raises(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.mp3"
        in_file.write_bytes(b"fake")
        with pytest.raises(SeparationError, match="Unknown model"):
            separate(in_file, tmp_path / "out", model="not_a_model")

    def test_missing_input_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            separate(tmp_path / "missing.mp3", tmp_path / "out")

    def test_runs_demucs_on_first_call(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("stemguessr.separate._run_demucs", _fake_run_demucs)
        in_file = tmp_path / "in.mp3"
        in_file.write_bytes(b"fake")
        output_dir = tmp_path / "out"

        result = separate(in_file, output_dir)

        assert set(result.keys()) == set(MODEL_STEMS["htdemucs"])
        for stem in MODEL_STEMS["htdemucs"]:
            expected = output_dir / f"{stem}.wav"
            assert result[stem] == expected
            assert expected.exists()

    def test_idempotent_when_all_outputs_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When all expected stem files already exist, _run_demucs must not be called."""
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        for stem in MODEL_STEMS["htdemucs"]:
            (output_dir / f"{stem}.wav").write_bytes(b"\x00" * 44)

        def _must_not_call(*args: object, **kwargs: object) -> dict[str, Path]:
            raise AssertionError("idempotent short-circuit failed: Demucs was invoked")

        monkeypatch.setattr("stemguessr.separate._run_demucs", _must_not_call)

        in_file = tmp_path / "in.mp3"
        in_file.write_bytes(b"fake")
        result = separate(in_file, output_dir)
        assert set(result.keys()) == set(MODEL_STEMS["htdemucs"])

    def test_partial_outputs_trigger_rerun(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If even one expected stem is missing, separation is re-run for the
        whole input. (Demucs does not support partial separation.)
        """
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "drums.wav").write_bytes(b"\x00" * 44)

        invoked = {"flag": False}

        def _wrapped(input_path: Path, output_dir: Path, model: str) -> dict[str, Path]:
            invoked["flag"] = True
            return _fake_run_demucs(input_path, output_dir, model)

        monkeypatch.setattr("stemguessr.separate._run_demucs", _wrapped)

        in_file = tmp_path / "in.mp3"
        in_file.write_bytes(b"fake")
        separate(in_file, output_dir)
        assert invoked["flag"], "expected re-run when only some stems present"

    def test_htdemucs_6s_produces_six_stems(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("stemguessr.separate._run_demucs", _fake_run_demucs)
        in_file = tmp_path / "in.mp3"
        in_file.write_bytes(b"fake")
        output_dir = tmp_path / "out"

        result = separate(in_file, output_dir, model="htdemucs_6s")

        assert len(result) == 6
        assert "guitar" in result
        assert "piano" in result
        for stem in MODEL_STEMS["htdemucs_6s"]:
            assert (output_dir / f"{stem}.wav").exists()
