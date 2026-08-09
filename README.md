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
│   │   ├── pipeline.py          # POST /pipeline/run  ← full chain in one call
│   │   └── quiz.py              # GET  /quiz/topics, /quiz/topics/{id}, /quiz/clips/{phrase}
│   ├── services/
│   │   ├── asr.py               # faster-whisper singleton + ffmpeg audio extraction
│   │   ├── gloss.py             # spaCy ISL grammar engine (rule-based)
│   │   ├── clip_lookup.py       # CISLR vocab loader + greedy longest-match lookup
│   │   ├── assembly.py          # per-clip adaptive trim + re-encode, then ffmpeg -c copy concat
│   │   └── quiz.py              # Quiz topic/question loader + clip resolution (own vocab read)
│   └── data/
│       └── quiz_data.json       # Hardcoded quiz topics/questions (5 topics, 30 questions)
├── frontend/
│   ├── index.html               # Two-column layout: upload left, results right
│   ├── style.css                # Dark navy + amber theme, Stage 7 polish complete
│   ├── app.js                   # Pipeline wiring, loading steps, results render
│   ├── quiz.html                # Quiz mode: topic select → question card → summary
│   ├── quiz.css                 # Quiz mode styling (same dark/amber palette)
│   └── quiz.js                  # Quiz flow, scoring, clip replay
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

## Quiz mode

A separate learning feature, fully independent of the main pipeline — reachable via the "Quiz mode →" link in the header (`http://localhost:8000/static/quiz.html`).

Fixed, hardcoded multiple-choice quiz: pick a topic, watch a sign clip, choose the correct meaning from 4 options, get instant correct/incorrect feedback, replay the clip if needed, move to the next question, see a score summary at the end. Session-only — no persistence, no accounts.

```
GET /quiz/topics             → [{ id, name, question_count }]
GET /quiz/topics/{topic_id}  → { topic_id, questions: [{ id, clip_phrase, options, correct_answer }] }
GET /quiz/clips/{phrase}     → streams the sign clip (resolved against the same ISL vocab JSON as the main pipeline)
```

Content lives in `backend/data/quiz_data.json` — currently 5 topics (Colors, Family, Animals, Numbers, Food), 6 questions each, distractors drawn from within the same topic. `backend/services/quiz.py` does its own read-only vocab lookup (same `ISL_VOCAB_PATH`/`trimmed_path` preference as `clip_lookup.py`) — it does not import or modify the main pipeline's clip lookup.

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

## Known gloss engine limitations

| Limitation | Detail |
|---|---|
| Complex compound nouns | Ordering within NPs of 3+ words can still be imperfect |
| Whisper `tiny` mishears | Occasionally mishears domain-specific words (e.g. "deaf" → "death", "spaCy" → "spacey") — model size tradeoff for speed |
| Reordered multi-word glosses | CISLR vocab stores phrases in English surface order, so ISL-reordered glosses (e.g. `YOU THANK` from "thank you") won't match the `THANK YOU` vocab entry |

## Known issues

| Issue | Detail |
|---|---|
| `outputs/` grows unbounded | No cleanup logic — fine for demo, add a TTL cleanup for production |
| `TemporaryDirectory` cleanup on Windows | Occasionally fails to delete if ffmpeg still holds a file handle — harmless, OS cleans up on restart |
| Stale `_vocab` singleton | Module-level in `clip_lookup.py` — a wrong `ISL_VOCAB_PATH` surfaces on first request, not at startup (lazy load) |
| `_normalize_clip()` re-encode + `-bf 0` required | Re-encoding every clip (not `-c copy`) with zero B-frames fixes a flicker at concat-demuxer boundaries — B-frame reordering leaves overlapping/non-monotonic `pts_time` at each join otherwise. Do not revert without re-verifying monotonic timestamps across a real multi-clip concat. |

---

## Dataset paths (this machine)

```
Vocab JSON:       C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_full.json
Normalized clips: C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_normalized\
Raw clips:        C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_raw\
CISLR metadata:   C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_meta\
```

These are also in `.env` (gitignored).
