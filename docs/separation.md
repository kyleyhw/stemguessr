# Source Separation with Hybrid Demucs

This document derives the algorithm wrapped by [`src/stemguessr/separate.py`](../src/stemguessr/separate.py): **Hybrid Demucs** (`htdemucs`, optionally `htdemucs_6s`), the model used to split each cached 30-second preview into its constituent instrumental stems. The aim is to make the *why* of the architecture and training objective recoverable from this document alone.

## 1. Problem statement

Let the observed mixture be a discrete-time signal $x[n] \in \mathbb{R}$, $n = 0, \ldots, N-1$. By construction, at recording time, the mixture is the sum of $K$ underlying *stem* signals $s_i[n]$:

$$
x[n] = \sum_{i=1}^{K} s_i[n].
$$

The source-separation problem is: given only $x[n]$, recover each $s_i[n]$. This is fundamentally ill-posed — countless decompositions satisfy the equation above — so all useful methods inject prior structure: about the spectro-temporal behaviour of each instrument, the statistical independence of stems, or learned representations from training data. Modern approaches are overwhelmingly the last kind.

For StemGuessr, $K = 4$ (drums, bass, vocals, other) under `htdemucs` or $K = 6$ under `htdemucs_6s` (drums, bass, vocals, other, guitar, piano). The signals are stereo at 44.1 kHz.

## 2. Two classical frameworks, briefly

### 2.1 Time-frequency masking

Compute the short-time Fourier transform (STFT)

$$
X(t, f) = \sum_{n=0}^{N-1} x[n] \, w[n - tH] \, e^{-i 2\pi f n / N_{\text{FFT}}},
$$

where $w$ is the analysis window and $H$ is the hop length. Predict a *mask* $M_i(t, f) \in \mathbb{C}$ for each source, then reconstruct via inverse STFT:

$$
\hat{S}_i(t, f) = M_i(t, f) \cdot X(t, f), \qquad
\hat{s}_i[n] = \mathrm{iSTFT}\{\hat{S}_i\}[n].
$$

When $M_i$ is restricted to be real-valued (a magnitude mask), the recovered source's phase is borrowed from the mixture, which empirically introduces audible artefacts on tonal content. Complex masks $M_i \in \mathbb{C}$ avoid this but expand the parameter space. STFT-domain methods are easy to learn but can be brittle on transients (drum hits) where time-localisation of the prediction matters more than frequency resolution.

### 2.2 Direct waveform regression

Pose the problem in the time domain:

$$
\hat{s}_i = f_\theta(x), \qquad \hat{s}_i \in \mathbb{R}^N,
$$

where $f_\theta$ is a deep convolutional network (typically a 1-D U-Net). The original Demucs [[1]](#ref-defossez-2019) used this approach. Time-domain models handle transients well — there is no phase reconstruction step — but they have historically lagged on long-horizon harmonic content where frequency-domain models excel.

The two frameworks have *complementary failure modes*. Hybrid Demucs exploits exactly that.

## 3. Hybrid Demucs

### 3.1 Architecture

Hybrid Demucs [[2]](#ref-defossez-2021) is a U-Net with **two parallel encoder–decoder branches** that exchange features at every depth:

- A **time-domain branch** $E_t / D_t$ that operates on $x \in \mathbb{R}^{C \times N}$ (channels × time).
- A **spectrogram branch** $E_f / D_f$ that operates on the complex STFT $X \in \mathbb{C}^{C \times F \times T}$ (channels × frequency × time-frame).

At each encoder depth $\ell$, latent features from the two branches are added (after a linear adapter to align channel counts):

$$
h_\ell = E_t^\ell(\cdot) + A_\ell\left(E_f^\ell(\cdot)\right),
$$

so the deeper layers of each branch see information from the other domain. The decoders mirror this exchange. The two branches' final outputs are summed *in the time domain* — the spectrogram branch's prediction is iSTFTed first — to give the per-source estimate:

$$
\hat{s}_i = D_t^{(i)}(h) + \mathrm{iSTFT}\left\{D_f^{(i)}(h)\right\}.
$$

The intuition: drum transients are best handled by $D_t$; sustained vocals and harmonic content are best handled by $D_f$. The linear cross-domain adapters $A_\ell$ are themselves learned, so the network discovers *where* in its hierarchy each domain dominates.

### 3.2 HT — adding transformers

`htdemucs` extends Hybrid Demucs by replacing the innermost few convolutional blocks of each branch with **transformer blocks** [[3]](#ref-rouard-2022). Self-attention provides global receptive field within the bottleneck; cross-attention between branches replaces the simple additive feature exchange at the deepest layers. Empirically this lifts performance on long-range harmonic content (sustained vocals, piano) where convolutions of the original Hybrid Demucs were under-resolving.

The resulting `htdemucs` is what `demucs.api.Separator` instantiates by default and what StemGuessr uses.

## 4. Training objective

Demucs and its descendants are trained on the MUSDB18-HQ corpus (and additional in-house data for HT) with a composite loss that mixes time- and frequency-domain reconstruction terms:

$$
\mathcal{L}(\theta) = \sum_{i=1}^{K} \left[
    \underbrace{\| \hat{s}_i - s_i \|_1}_{\mathcal{L}_1, \text{ time-domain}}
    \;+\;
    \lambda \,
    \underbrace{\sum_{r=1}^{R} \big\| |\mathrm{STFT}_r\{\hat{s}_i\}| - |\mathrm{STFT}_r\{s_i\}| \big\|_1}_{\mathcal{L}_{\text{stft}}, \text{ multi-resolution magnitude}}
\right].
$$

The L1 term penalises sample-level reconstruction error; the multi-resolution STFT term [[4]](#ref-yamamoto-2020) penalises magnitude-spectrogram error at several FFT sizes $r \in \{1, \ldots, R\}$ simultaneously, which prevents the network from over-smoothing one resolution at the cost of another. The mixing coefficient $\lambda$ is fixed at training time. Demucs uses no adversarial term, and no perceptual loss beyond multi-resolution STFT — the hybrid architecture's inductive bias is doing most of the work.

## 5. Why `htdemucs` over baseline Demucs

For comparable-or-smaller parameter count, `htdemucs` improves the standard MUSDB18 SDR (Source-to-Distortion Ratio) by approximately 0.5–1.0 dB across all four stems versus the previous Hybrid Demucs (no transformers), and by 1–2 dB versus the original waveform-only Demucs [[3]](#ref-rouard-2022). For a guessing game where audible quality of stems matters more than every dB of SDR, the difference is most noticeable on `vocals` (which become more isolated, less bleeding from harmonic backing) and on `other` (cleaner residual). Inference cost is comparable on CPU.

## 6. Four-stem vs six-stem

`htdemucs_6s` further splits the residual `other` stem into `guitar` and `piano`. This is useful when a track's character is dominated by one of those instruments, but comes with caveats:

- The 6-stem model is trained on a smaller corpus and shows somewhat lower SDR per stem than `htdemucs`.
- Tracks with no guitar or no piano produce near-silent stems in those slots; the game UI should detect and downrank such stems for guessing.
- `other` in the 6-stem model is a *true* residual ("everything except the named five"); its character changes vs the 4-stem model.

StemGuessr defaults to `htdemucs` (4-stem, 4 guesses). `htdemucs_6s` is opt-in via the CLI's `--stems 6` flag (Phase 6). In future iterations, more than 6 guesses with `htdemucs_6s` is a natural extension of the game format.

## 7. Limitations under the 30-second-preview constraint

StemGuessr's audio source is the 30-second preview from iTunes or Deezer (Phase 3). Two consequences flow from that:

1. **Short context.** Demucs's transformer self-attention has a global receptive field within the input it receives, so 30 s is enough for the model to attend everywhere; there is no information lost relative to a longer clip. SDR on a 30-second slice is essentially identical to SDR on the full track from which it was cut, all else equal.
2. **Source-side compression.** Both iTunes (AAC at ~96 kbps in M4A) and Deezer (MP3 at 128 kbps) deliver lossy audio. Demucs ingests it without complaint, but the resulting stems inherit those compression artefacts. `vocals` is the most affected (sibilance at the AAC mid-band notch); `drums` is the least. The trade-off is acceptable for a guessing game but would be unsuitable for archival separation.

## 8. Wrapper design (this codebase)

The wrapper in [`src/stemguessr/separate.py`](../src/stemguessr/separate.py) is intentionally thin:

```python
def separate(input_path, output_dir, *, model="htdemucs") -> dict[str, Path]:
    if model not in MODEL_STEMS:
        raise SeparationError(...)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    expected = {name: output_dir / f"{name}.wav" for name in MODEL_STEMS[model]}
    if all(p.exists() for p in expected.values()):
        return expected               # idempotent short-circuit
    return _run_demucs(input_path, output_dir, model)
```

Three design choices worth flagging:

- **Idempotency by file existence**, not by content hash. Re-runs over the same playlist are essentially free; a corrupted stem on disk is *not* detected — the user must `rm` it manually. This is the right trade-off given separation is deterministic and stems are large.
- **Lazy imports of torch / demucs / torchaudio** inside `_run_demucs`, so importing `stemguessr.separate` itself does not pay torch's ~1 s startup cost.
- **`_run_demucs` as a monkeypatchable seam.** Tests replace it with a stub that writes 44-byte WAV placeholders, avoiding the multi-hundred-MB model download and slow CPU inference path.

## 9. Testing

Tests in [`tests/test_separate.py`](../tests/test_separate.py) cover:

- Stem catalogue agrees with documentation (4-stem and 6-stem cases).
- Unknown model raises `SeparationError`.
- Missing input file raises `FileNotFoundError`.
- First call writes all expected stems.
- Second call with all outputs present is a no-op (asserts `_run_demucs` is *not* called).
- Partial outputs trigger a re-run.
- 6-stem mode produces six paths with `guitar` and `piano`.

A genuine end-to-end Demucs run against a real WAV fixture is deferred to Phase 8 (Integration & Polish), behind an opt-in environment variable, since it requires a multi-hundred-MB model download.

The latest test report is at [`../tests/reports/phase4_separate.md`](../tests/reports/phase4_separate.md).

## References

<span id="ref-defossez-2019">[1]</span> Défossez, A., Usunier, N., Bottou, L., & Bach, F. (2019). *Music Source Separation in the Waveform Domain.* arXiv:1911.13254. [Link](https://arxiv.org/abs/1911.13254)

<span id="ref-defossez-2021">[2]</span> Défossez, A. (2021). *Hybrid Spectrogram and Waveform Source Separation.* In *MDX Workshop at ISMIR 2021*. [Link](https://arxiv.org/abs/2111.03600)

<span id="ref-rouard-2022">[3]</span> Rouard, S., Massa, F., & Défossez, A. (2022). *Hybrid Transformers for Music Source Separation.* arXiv:2211.08553. [Link](https://arxiv.org/abs/2211.08553)

<span id="ref-yamamoto-2020">[4]</span> Yamamoto, R., Song, E., & Kim, J.-M. (2020). *Parallel WaveGAN: A fast waveform generation model based on generative adversarial networks with multi-resolution spectrogram.* In *ICASSP 2020.* [Link](https://arxiv.org/abs/1910.11480)

<span id="ref-musdb18">[5]</span> Rafii, Z., Liutkus, A., Stöter, F.-R., Mimilakis, S. I., & Bittner, R. (2017). *MUSDB18 — a corpus for music separation.* [Link](https://sigsep.github.io/datasets/musdb.html)
