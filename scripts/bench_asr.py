"""
ASR benchmark harness — measures speed, accuracy, and VRAM for the ASR stage
in isolation (no HTTP, no ffmpeg concat, no gloss) so the numbers are clean
enough for the paper.

Reports per backend/device:
  - WER   : word error rate vs. ground-truth transcripts (accuracy; lower is better)
  - RTFx  : audio-seconds processed per wall-second (throughput; higher is better)
  - VRAM  : peak GPU memory used by this process (GPU runs only)
  - Load  : one-time model load time
  - Proc  : total inference wall-time over the test set (excludes load/warmup)

Design notes:
  - Calls the model directly, not /pipeline/run — network + video handling +
    clip assembly would pollute the timing. This measures ASR only.
  - A warmup utterance runs before timing on each backend: the first CUDA call
    compiles kernels and would otherwise make the first clip look 10x slower.
  - Whisper decode params mirror backend/services/asr.py so numbers reflect the
    app's real behavior, not a different config.
  - Two engines: Whisper (faster-whisper) and Parakeet (NVIDIA NeMo). Parakeet
    lives in a separate venv (venv-nemo) because NeMo pulls torch + a large
    dependency tree we keep out of the app env — run its benchmark with that
    venv's python. The harness, datasets, metrics, and table code are shared.

Usage:
  python -m scripts.bench_asr                       # Whisper, CPU + GPU, LibriSpeech (100 clips)
  python -m scripts.bench_asr --device cuda         # GPU only
  python -m scripts.bench_asr --limit 0             # whole test set (paper run)
  python -m scripts.bench_asr --model large-v3      # a different Whisper size
  python -m scripts.bench_asr --dataset dir --data-dir path/to/my_clips
      # custom set: each audio file X.wav paired with X.txt holding its transcript

  # Parakeet (from the NeMo venv):
  .\\venv-nemo\\Scripts\\python.exe -m scripts.bench_asr --engine parakeet --device cuda
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tarfile
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Allow "python scripts/bench_asr.py" as well as "-m scripts.bench_asr"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = _PROJECT_ROOT / "benchmark_data"     # gitignored
RESULTS_DIR = _PROJECT_ROOT / "benchmark_data" / "results"

LIBRISPEECH_URL = "https://www.openslr.org/resources/12/test-clean.tar.gz"
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus"}


# ---------------------------------------------------------------------------
# Backend abstraction — one subclass per ASR engine (Whisper now, Parakeet later)
# ---------------------------------------------------------------------------

class AsrBackend(ABC):
    """An ASR engine bound to a device. load() once, then transcribe() per clip."""
    name: str
    device: str

    @abstractmethod
    def load(self) -> None:
        """Load the model onto the device. Called once, timed as 'load'."""

    @abstractmethod
    def transcribe(self, audio_path: Path) -> Tuple[str, float]:
        """Return (transcript_text, audio_duration_seconds) for one clip."""


class WhisperBackend(AsrBackend):
    def __init__(self, device: str, model_size: str):
        self.name = f"faster-whisper:{model_size}"
        self.device = device
        self._model_size = model_size
        self._model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel
        from backend.services.asr import _register_cuda_dll_dirs, _compute_type_for

        if self.device == "cuda":
            _register_cuda_dll_dirs()
        self._model = WhisperModel(
            self._model_size,
            device=self.device,
            compute_type=_compute_type_for(self.device),
        )

    def transcribe(self, audio_path: Path) -> Tuple[str, float]:
        # Mirror the app's decode settings (backend/services/asr.py).
        segments, info = self._model.transcribe(
            str(audio_path),
            beam_size=5,
            language="en",
            condition_on_previous_text=True,
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip())
        return text, float(info.duration)


# Default Parakeet model (NVIDIA NeMo, English). Overridable via --model with
# any NeMo ASR .nemo repo id. This is the flagship NVIDIA benchmarks vs Whisper.
PARAKEET_DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v2"


class ParakeetBackend(AsrBackend):
    """
    NVIDIA Parakeet (NeMo) backend. Lives in a SEPARATE venv (venv-nemo) from
    the app — NeMo drags in torch + a large dependency tree we deliberately keep
    out of the FastAPI app environment. Run via:
        .\\venv-nemo\\Scripts\\python.exe -m scripts.bench_asr --engine parakeet

    Loads the local cached .nemo (downloaded once via huggingface_hub) with
    ASRModel.restore_from — no re-download, no dependency on NeMo's own model
    registry. torch must be CUDA-enabled for the GPU run to be meaningful.
    """
    def __init__(self, device: str, model_id: str):
        short = model_id.split("/")[-1]
        self.name = f"parakeet:{short}"
        self.device = device
        self._model_id = model_id
        self._model = None

    def load(self) -> None:
        from huggingface_hub import hf_hub_download
        from nemo.collections.asr.models import ASRModel

        # Resolve the cached .nemo path (instant if already downloaded).
        nemo_file = f"{self._model_id.split('/')[-1]}.nemo"
        local_path = hf_hub_download(repo_id=self._model_id, filename=nemo_file)

        map_location = "cuda" if self.device == "cuda" else "cpu"
        self._model = ASRModel.restore_from(local_path, map_location=map_location)
        self._model.eval()

    def transcribe(self, audio_path: Path) -> Tuple[str, float]:
        import soundfile as sf

        info = sf.info(str(audio_path))
        duration = float(info.frames) / float(info.samplerate)

        # NeMo returns a list (one entry per input). Depending on version each
        # entry is a Hypothesis (with .text) or a plain string — handle both.
        out = self._model.transcribe([str(audio_path)], batch_size=1, verbose=False)
        item = out[0]
        text = getattr(item, "text", item)
        return str(text).strip(), duration


# Register available backends here.
def build_backend(engine: str, device: str, model_size: str) -> AsrBackend:
    if engine == "whisper":
        return WhisperBackend(device, model_size)
    if engine == "parakeet":
        # --model defaults to "small" (a Whisper size); treat that as "use the
        # Parakeet default", but honor an explicit NeMo repo id if given.
        model_id = model_size if "/" in model_size else PARAKEET_DEFAULT_MODEL
        return ParakeetBackend(device, model_id)
    raise ValueError(f"Unknown engine {engine!r}. Known: whisper, parakeet.")


# ---------------------------------------------------------------------------
# VRAM sampling (GPU runs only) — via nvidia-ml-py (pynvml)
# ---------------------------------------------------------------------------

class VramSampler:
    """Per-process GPU memory in MB. No-op / None when unavailable or on CPU."""

    def __init__(self, gpu_index: int = 0):
        self._ok = False
        self._handle = None
        try:
            import pynvml  # from the nvidia-ml-py package
            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
            self._ok = True
        except Exception:
            self._ok = False

    def used_mb(self) -> Optional[float]:
        if not self._ok:
            return None
        try:
            procs = self._pynvml.nvmlDeviceGetComputeRunningProcesses(self._handle)
            mypid = os.getpid()
            for p in procs:
                if p.pid == mypid and p.usedGpuMemory:
                    return p.usedGpuMemory / (1024 * 1024)
            # Fallback: whole-device used (less precise, e.g. if PID not listed)
            info = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            return info.used / (1024 * 1024)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Metrics — WER
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Basic normalization for WER: lowercase, drop punctuation, collapse spaces.
    (Not OpenAI's full English normalizer — enough for a fair A/B between
    backends run through the same function; note this in the paper.)"""
    out = []
    for ch in text.lower():
        if ch.isalnum() or ch.isspace():
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def compute_wer(references: List[str], hypotheses: List[str]) -> float:
    import jiwer
    refs = [_normalize(r) for r in references]
    hyps = [_normalize(h) for h in hypotheses]
    # Drop empty references (would make WER undefined for that line)
    pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
    if not pairs:
        return float("nan")
    refs, hyps = zip(*pairs)
    return float(jiwer.wer(list(refs), list(hyps)))


# ---------------------------------------------------------------------------
# Datasets — return list of (audio_path, reference_text)
# ---------------------------------------------------------------------------

def _download_with_progress(url: str, dest: Path) -> None:
    print(f"Downloading {url}\n  -> {dest}")

    def hook(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(100, block_num * block_size * 100 / total_size)
            mb = block_num * block_size / (1024 * 1024)
            print(f"\r  {pct:5.1f}%  ({mb:.0f} MB)", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=hook)
    print()


def load_librispeech(data_dir: Path) -> List[Tuple[Path, str]]:
    """Download (once) and parse LibriSpeech test-clean into (flac, reference) pairs."""
    data_dir.mkdir(parents=True, exist_ok=True)
    extracted = data_dir / "LibriSpeech" / "test-clean"

    if not extracted.exists():
        tar_path = data_dir / "test-clean.tar.gz"
        if not tar_path.exists():
            _download_with_progress(LIBRISPEECH_URL, tar_path)
        print("Extracting test-clean.tar.gz ...")
        with tarfile.open(tar_path) as tf:
            tf.extractall(data_dir)
        print("Extracted.")

    pairs: List[Tuple[Path, str]] = []
    for trans in extracted.rglob("*.trans.txt"):
        for line in trans.read_text(encoding="utf-8").splitlines():
            if " " not in line:
                continue
            uid, text = line.split(" ", 1)
            flac = trans.parent / f"{uid}.flac"
            if flac.exists():
                pairs.append((flac, text.strip()))
    return pairs


def load_custom_dir(data_dir: Path) -> List[Tuple[Path, str]]:
    """Custom set: every audio file X.<ext> paired with X.txt holding its transcript."""
    pairs: List[Tuple[Path, str]] = []
    if not data_dir.exists():
        raise FileNotFoundError(f"--data-dir does not exist: {data_dir}")
    for audio in sorted(data_dir.iterdir()):
        if audio.suffix.lower() not in _AUDIO_EXTS:
            continue
        txt = audio.with_suffix(".txt")
        if not txt.exists():
            print(f"  (skipping {audio.name}: no matching {txt.name} transcript)")
            continue
        pairs.append((audio, txt.read_text(encoding="utf-8").strip()))
    if not pairs:
        raise RuntimeError(
            f"No audio+.txt pairs found in {data_dir}. "
            "Each clip X.wav needs a sibling X.txt with its transcript."
        )
    return pairs


# ---------------------------------------------------------------------------
# Benchmark run
# ---------------------------------------------------------------------------

@dataclass
class BenchResult:
    backend: str
    device: str
    num_clips: int
    audio_seconds: float
    proc_seconds: float
    rtfx: float
    wer: float
    load_seconds: float
    peak_vram_mb: Optional[float]


def run_backend(
    backend: AsrBackend,
    clips: List[Tuple[Path, str]],
) -> BenchResult:
    print(f"\n=== {backend.name} on {backend.device.upper()} ===")
    vram = VramSampler() if backend.device == "cuda" else None

    t0 = time.perf_counter()
    backend.load()
    load_seconds = time.perf_counter() - t0
    print(f"  loaded in {load_seconds:.1f}s")

    peak_vram = vram.used_mb() if vram else None

    # Warmup on the first clip — not counted (kernel compilation, caches).
    print("  warmup ...")
    backend.transcribe(clips[0][0])
    if vram:
        v = vram.used_mb()
        if v is not None:
            peak_vram = max(peak_vram or 0.0, v)

    references: List[str] = []
    hypotheses: List[str] = []
    total_audio = 0.0
    total_proc = 0.0

    for i, (audio_path, ref) in enumerate(clips, 1):
        t = time.perf_counter()
        hyp, audio_sec = backend.transcribe(audio_path)
        proc = time.perf_counter() - t
        total_proc += proc
        total_audio += audio_sec
        references.append(ref)
        hypotheses.append(hyp)
        if vram:
            v = vram.used_mb()
            if v is not None:
                peak_vram = max(peak_vram or 0.0, v)
        if i % 20 == 0 or i == len(clips):
            print(f"  {i}/{len(clips)} clips  (RTFx so far: {total_audio / total_proc:.1f})")

    rtfx = total_audio / total_proc if total_proc > 0 else 0.0
    wer = compute_wer(references, hypotheses)

    return BenchResult(
        backend=backend.name,
        device=backend.device,
        num_clips=len(clips),
        audio_seconds=round(total_audio, 1),
        proc_seconds=round(total_proc, 1),
        rtfx=round(rtfx, 2),
        wer=round(wer, 4),
        load_seconds=round(load_seconds, 1),
        peak_vram_mb=round(peak_vram, 0) if peak_vram is not None else None,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_table(results: List[BenchResult]) -> None:
    headers = ["Backend", "Device", "Clips", "Audio(s)", "Proc(s)", "RTFx", "WER%", "Load(s)", "VRAM(MB)"]
    rows = []
    for r in results:
        rows.append([
            r.backend,
            r.device.upper(),
            str(r.num_clips),
            f"{r.audio_seconds:.0f}",
            f"{r.proc_seconds:.1f}",
            f"{r.rtfx:.2f}",
            f"{r.wer * 100:.2f}" if r.wer == r.wer else "n/a",  # NaN check
            f"{r.load_seconds:.1f}",
            f"{r.peak_vram_mb:.0f}" if r.peak_vram_mb is not None else "n/a",
        ])
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print("\n" + line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def save_json(results: List[BenchResult], meta: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"bench_{stamp}.json"
    out.write_text(
        json.dumps({"meta": meta, "results": [asdict(r) for r in results]}, indent=2),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="ASR benchmark (Whisper; Parakeet-ready).")
    ap.add_argument("--engine", default="whisper", choices=["whisper", "parakeet"],
                    help="ASR engine to benchmark. 'parakeet' must run from venv-nemo.")
    ap.add_argument("--device", default="both", choices=["cpu", "cuda", "both"],
                    help="Device(s) to run. 'both' = CPU then GPU.")
    ap.add_argument("--model", default="small",
                    help="Whisper model size (tiny|base|small|medium|large-v3).")
    ap.add_argument("--dataset", default="librispeech", choices=["librispeech", "dir"],
                    help="'librispeech' auto-downloads; 'dir' uses --data-dir of X.wav+X.txt pairs.")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="For --dataset dir: folder of audio+.txt. For librispeech: download cache.")
    ap.add_argument("--limit", type=int, default=100,
                    help="Max clips to run (0 = all). Kept small for quick iteration.")
    ap.add_argument("--seed", type=int, default=42, help="Sampling seed for reproducibility.")
    args = ap.parse_args()

    # --- Load dataset ---
    if args.dataset == "librispeech":
        data_dir = args.data_dir or DEFAULT_DATA_DIR
        clips = load_librispeech(data_dir)
    else:
        if args.data_dir is None:
            ap.error("--dataset dir requires --data-dir")
        clips = load_custom_dir(args.data_dir)

    random.Random(args.seed).shuffle(clips)
    if args.limit > 0:
        clips = clips[: args.limit]
    print(f"Test set: {len(clips)} clips ({args.dataset})")

    # --- Devices ---
    devices = ["cpu", "cuda"] if args.device == "both" else [args.device]

    results: List[BenchResult] = []
    for device in devices:
        backend = build_backend(args.engine, device, args.model)
        try:
            results.append(run_backend(backend, clips))
        except Exception as exc:
            print(f"  !! {backend.name} on {device.upper()} failed: "
                  f"{type(exc).__name__}: {str(exc)[:200]}")
            if device == "cuda":
                print("     (CUDA libraries or driver issue — CPU results above still valid.)")

    if not results:
        print("\nNo successful runs.")
        return

    print_table(results)
    meta = {
        "engine": args.engine, "model": args.model, "dataset": args.dataset,
        "limit": args.limit, "num_clips": len(clips), "seed": args.seed,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    out = save_json(results, meta)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
