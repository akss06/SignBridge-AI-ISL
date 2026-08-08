# SignBridge AI

> Converts pre-recorded English audio or video into Indian Sign Language (ISL) signed video output.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn (Python 3.13) |
| Speech-to-text | faster-whisper 1.2.1 — Whisper `tiny`, CPU/int8 |
| Gloss engine | spaCy 3.8.x `en_core_web_sm`, rule-based ISL grammar only |
| Clip dataset | CISLR v1.5 — 4,765 ISL signs, pre-normalized h264/640×480/25fps |
| Video assembly | ffmpeg — `-c copy` concat, no re-encode |
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
│       └── assembly.py          # ffmpeg -c copy concat
├── frontend/
│   ├── index.html               # Two-column layout: upload left, results right
│   ├── style.css                # Dark navy + amber theme (Stage 7 polish pending)
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

### Stage 7 — Styling pass (not yet started)
The CSS in `frontend/style.css` is functional but not polished. The brief:
- Dark navy (`#0d1b2a`) background with amber (`#f59e0b`) accent — already in place
- Clean two-column layout: video on the right, gloss/coverage/transcript on the right column
- Polish the loading spinner and step indicators
- Polish the gloss chip presentation
- No functional changes — CSS only
- Keep vanilla CSS, no frameworks

### trim_clips.py — adaptive threshold (partially done, not verified)
The offline clip-trimming script exists at `trim_clips.py` and has been dry-run tested on 30 demo clips. The current fixed threshold (`MOTION_THRESHOLD = 0.008`) produces two failure modes:
- **NEAR_ZERO_LENGTH** — threshold too high for gentle-motion clips (pronouns like I, HE)
- **BARELY_TRIMMED** — threshold too low for high-motion clips, nothing gets trimmed

**Needed:** Replace fixed threshold with per-clip adaptive thresholding — compute the score distribution per clip and set the trim threshold at the ~30th percentile of that clip's own scores. Then re-run `--subset --dry-run`, verify results look sane, then run `--subset` (no dry-run) to write the 30 trimmed clips, spot-check them, and finally ask before running `--full` on all 4,765.

Once trimmed clips are verified, update `backend/services/clip_lookup.py` to prefer `trimmed_path` over `normalized_path` when loading the vocab index. The trimmed vocab JSON is written to `isl_vocab_trimmed.json` by the script.

### Known gloss engine limitations (acceptable for MVP, document for judges)
- Compound noun ordering within complex NPs can still be imperfect for 3+ word compounds
- Whisper `tiny` occasionally mishears domain-specific words (e.g. "deaf" → "death", "spaCy" → "spacey") — model size tradeoff for speed
- CISLR vocab stores phrases in English surface order, so ISL-reordered multi-word glosses (e.g. `YOU THANK` from "thank you") won't match the `THANK YOU` vocab entry

### Known issues — do NOT change without reading the notes
- `outputs/` fills up with generated videos — no cleanup logic exists. Fine for demo, add a TTL cleanup for production.
- Assembly uses `tempfile.TemporaryDirectory` — on Windows, this occasionally fails to delete if ffmpeg holds a file handle. Harmless (OS cleans up on restart) but worth noting.
- `_vocab` singleton in `clip_lookup.py` is module-level — if `ISL_VOCAB_PATH` is wrong, the error surfaces on first request, not at startup. Intentional (lazy load), but confusing for debugging.

---

## Dataset paths (this machine)

```
Vocab JSON:       C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_full.json
Normalized clips: C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_normalized\
Raw clips:        C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_raw\
CISLR metadata:   C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_meta\
```

These are also in `.env` (gitignored).
