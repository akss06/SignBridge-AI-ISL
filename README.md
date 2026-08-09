# SignBridge AI

> Converts pre-recorded English audio or video into Indian Sign Language (ISL) signed video output.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn (Python 3.13) |
| Speech-to-text | faster-whisper 1.2.1 — Whisper `tiny`, CPU/int8 |
| Gloss engine | spaCy 3.8.x `en_core_web_sm`, rule-based ISL grammar only |
| Clip dataset | CISLR v1.5 — 4,765 ISL signs, pre-normalized h264/640×480/25fps |
| Video assembly | ffmpeg — per-clip adaptive trim + re-encode, then `-c copy` concat |
| Frontend | Vanilla HTML / CSS / JS — no framework, no build step |

## Prerequisites

- Python 3.13 (project was built and tested on 3.13.2)
- ffmpeg on PATH (or set `FFMPEG_BIN` in `.env`)
- CISLR dataset — normalized clips + vocab JSON (see `.env.example` for paths)

## Setup (Windows — no MSVC/Rust build tools needed)

```powershell
python -m venv venv
venv\Scripts\activate

# Install binary deps first (no C/Rust compilation required)
pip install "av>=15" --only-binary :all:
pip install "tokenizers>=0.21,<1" --only-binary :all:
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Copy and fill in dataset paths
copy .env.example .env
# Edit .env: set ISL_VOCAB_PATH and ISL_CLIPS_DIR
```

## Run

```powershell
.\venv\Scripts\uvicorn.exe backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

## Environment variables (`.env`)

```
ISL_VOCAB_PATH=<abs path to isl_vocab_full.json>
ISL_CLIPS_DIR=<abs path to cislr_normalized/>
FFMPEG_BIN=ffmpeg          # or full path if not on PATH
WHISPER_MODEL_SIZE=tiny    # tiny | base | small
HF_HUB_DISABLE_SYMLINKS_WARNING=1
```

---

## Project structure

```
SignBridge AI/
├── backend/
│   ├── main.py                  # FastAPI app — mounts /static, /outputs, registers routers
│   ├── schemas.py               # Shared Pydantic models: GlossToken, SentenceResult, PipelineResult
│   ├── routes/
│   │   ├── health.py            # GET  /health
│   │   ├── asr.py               # POST /asr/transcribe
│   │   ├── gloss.py             # POST /gloss/generate
│   │   ├── lookup.py            # POST /lookup/clips
│   │   ├── assembly.py          # POST /assembly/assemble
│   │   └── pipeline.py          # POST /pipeline/run  ← full chain in one call
│   └── services/
│       ├── asr.py               # faster-whisper singleton + ffmpeg audio extraction
│       ├── gloss.py             # spaCy ISL grammar engine (rule-based)
│       ├── clip_lookup.py       # CISLR vocab loader + greedy longest-match lookup
│       └── assembly.py          # per-clip adaptive trim + re-encode, then ffmpeg -c copy concat
├── frontend/
│   ├── index.html               # Two-column layout: upload left, results right
│   ├── style.css                # Dark navy + amber theme, Stage 7 polish complete
│   └── app.js                   # Pipeline wiring, loading steps, results render
├── trim_clips.py                # Offline utility: trim idle padding from CISLR clips
├── outputs/                     # Generated ISL videos (gitignored)
├── .env                         # Local config (gitignored)
├── .env.example                 # Template for .env
├── requirements.txt
└── README.md
```

---

## API — full pipeline (primary endpoint)

```
POST /pipeline/run
Content-Type: multipart/form-data
Body: file=<.wav | .mp3 | .mp4>
```

Runs all stages in sequence and returns a `PipelineResult`:

```json
{
  "transcript": "She drinks water.",
  "sentences": [
    {
      "original": "She drinks water.",
      "gloss_tokens": [
        { "token": "SHE",   "surface": null,    "clip_path": "/…/SHE.mp4",   "matched": true },
        { "token": "WATER", "surface": null,    "clip_path": "/…/WATER.mp4", "matched": true },
        { "token": "DRINK", "surface": "DRINKS","clip_path": "/…/DRINK.mp4", "matched": true }
      ]
    }
  ],
  "coverage": 1.0,
  "output_video_url": "/outputs/result_<uuid>.mp4",
  "error": null
}
```

Individual stage endpoints also exist: `/asr/transcribe`, `/gloss/generate`, `/lookup/clips`, `/assembly/assemble`.

---

## ISL grammar rules implemented (`backend/services/gloss.py`)

Based on Zeshan (2000) *Indo-Pakistani Sign Language Grammar* and computational ISL literature:

| Rule | Status |
|---|---|
| Time → Subject → Object → Verb word order | ✅ |
| Adjective after noun (`red ball` → `BALL RED`) | ✅ |
| Compound modifier after head noun (`video games` → `GAME VIDEO`) | ✅ |
| Negation marker at end of clause | ✅ |
| Clause splitting before reordering (compound/subordinate/complement) | ✅ |
| Function word dropping (articles, copulas, auxiliaries, prepositions, possessives) | ✅ |
| Surface-form fallback in clip lookup (`games` lemma=`GAME` miss → `GAMES` surface hit) | ✅ |
| WH-word repositioning | ❌ intentionally omitted — Zeshan is ambiguous |
| Fingerspelling for unmatched tokens | ❌ out of scope — tokens are dropped |

---

## What still needs doing — handoff notes for next session

### Stage 7 — Styling pass — ✅ done
Spinner/step-indicator and gloss-chip polish are complete in `frontend/style.css` (CSS-only, no markup/JS changes). Loading steps render as a connected dot-tracker instead of a generic spinner; gloss chips use a monospace face, a ✓ on matched signs, and a dashed "ghost" style for dropped ones.

### trim_clips.py — adaptive threshold — ✅ done, full corpus trimmed
The fixed `MOTION_THRESHOLD = 0.008` global threshold produced two failure modes (`NEAR_ZERO_LENGTH` on gentle clips like pronouns, `BARELY_TRIMMED` on high-motion ones). Replaced with a per-clip adaptive threshold — see `MOTION_PERCENTILE` in `trim_clips.py`.

Note the percentile is **90th**, not the ~30th originally guessed in this file: real hand-motion is a narrow spike at the top of a clip's own scene-score distribution, so a low percentile lets ordinary compression noise through as "active" and barely trims anything.

All 4,765 clips have been trimmed. Full-run results: 23,782s → 14,717s total (**38.1% saved**), 0 hard errors, 239 non-fatal `BARELY_TRIMMED`/`NO_TRIM_APPLIED` warnings (clips with genuinely continuous motion, correctly left untrimmed) — see `trim_log.json`. `isl_vocab_trimmed.json` has `trimmed_path` for all 4,765 entries.

`backend/services/clip_lookup.py` now prefers `trimmed_path` (falls back to `normalized_path`, then uid reconstruction). `backend/services/assembly.py`'s request-time step no longer does motion-based trimming — clips arrive pre-trimmed, so it only re-encodes each clip to normalize encoding parameters before concat (see `_normalize_clip` and the "Known issues" note below for why that re-encode step still exists and what it actually fixes).

**Still open:**
- Per-request latency: `_normalize_clip()` runs sequentially per clip in `assemble_video()`. Parallelizing with `ThreadPoolExecutor(max_workers=8)` measured ~3.4x faster in testing — not implemented, deprioritized for now.
- If a FastAPI server process was already running before the full trim finished, its in-memory `_vocab` singleton is stale (loaded from the pre-trim vocab) until restart — lazy singleton, no auto-invalidation.

### Known gloss engine limitations (acceptable for MVP, document for judges)
- Compound noun ordering within complex NPs can still be imperfect for 3+ word compounds
- Whisper `tiny` occasionally mishears domain-specific words (e.g. "deaf" → "death", "spaCy" → "spacey") — model size tradeoff for speed
- CISLR vocab stores phrases in English surface order, so ISL-reordered multi-word glosses (e.g. `YOU THANK` from "thank you") won't match the `THANK YOU` vocab entry

### Known issues — do NOT change without reading the notes
- `outputs/` fills up with generated videos — no cleanup logic exists. Fine for demo, add a TTL cleanup for production.
- Assembly uses `tempfile.TemporaryDirectory` — on Windows, this occasionally fails to delete if ffmpeg holds a file handle. Harmless (OS cleans up on restart) but worth noting.
- `_vocab` singleton in `clip_lookup.py` is module-level — if `ISL_VOCAB_PATH` is wrong, the error surfaces on first request, not at startup. Intentional (lazy load), but confusing for debugging.
- `assembly.py`'s `_normalize_clip()` re-encodes every clip (`libx264`, not `-c copy`) before the final concat, with **`-bf 0` (zero B-frames) required**. This is deliberate, not an oversight, and it took two rounds to get right:
  1. Concatenating clips pulled from differing source encodes caused a visible flash/flicker at each cut when stream-copied directly — re-encoding to identical parameters was the first fix.
  2. That alone wasn't enough — flicker persisted. Root cause (found via `ffprobe -show_entries frame=pts_time,pkt_dts_time,key_frame`): B-frame reordering leaves a decode/display buffer that doesn't reset cleanly at a concat-demuxer file boundary, producing overlapping/non-monotonic `pts_time` at every join even with matching encode parameters. `-bf 0` forces decode order to equal display order per segment, which fixed it — verified 0 non-monotonic timestamp transitions across a multi-clip concat afterward.

  `_normalize_clip()` also raises `RuntimeError` on a failed re-encode rather than silently falling back to the original clip — a silent fallback would put one non-normalized (and possibly B-frame-containing) segment next to normalized ones, reintroducing the flicker for just that boundary.

  Don't revert any of this (re-encode, `-bf 0`, or the raise-on-failure) without re-checking frame timestamps are monotonic across a real multi-clip concat output.

---

## Dataset paths (this machine)

```
Vocab JSON:       C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_full.json
Normalized clips: C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_normalized\
Raw clips:        C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_raw\
CISLR metadata:   C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_meta\
```

These are also in `.env` (gitignored).
