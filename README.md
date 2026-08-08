# SignBridge AI

> Converts pre-recorded English audio or video into Indian Sign Language (ISL) signed video output.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Speech-to-text | faster-whisper (Whisper base, CPU/int8) |
| Gloss engine | spaCy `en_core_web_sm`, rule-based ISL grammar |
| Video assembly | ffmpeg (must be on PATH, or set `FFMPEG_BIN` env var) |
| Frontend | Vanilla HTML / CSS / JS — no build step |

## Prerequisites

- Python 3.11+
- ffmpeg on PATH (or set `FFMPEG_BIN=/path/to/ffmpeg`)
- CISLR dataset clips + vocab JSON (provided separately — configure paths in Stage 4)

## Setup

```powershell
python -m venv venv
venv\Scripts\activate

# On Windows (no MSVC / Rust build tools), install av and tokenizers with
# pre-built wheels first, then the rest of the deps:
pip install "av>=15" --only-binary :all:
pip install "tokenizers>=0.21,<1" --only-binary :all:
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## Run

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000

## Project structure

```
SignBridge AI/
├── backend/
│   ├── main.py          # FastAPI app, static mounts
│   ├── schemas.py       # Shared Pydantic models (PipelineResult, etc.)
│   └── routes/
│       └── health.py    # GET /health
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── outputs/             # Generated ISL videos (not committed)
├── requirements.txt
└── README.md
```

## API contract

All pipeline endpoints return (or accept) the `PipelineResult` shape defined in
`backend/schemas.py`:

```json
{
  "transcript": "...",
  "sentences": [
    {
      "original": "...",
      "gloss_tokens": [
        { "token": "TOMORROW", "clip_path": "/path/clip.mp4", "matched": true }
      ]
    }
  ],
  "coverage": 0.85,
  "output_video_url": "/outputs/result_<uuid>.mp4",
  "error": null
}
```
