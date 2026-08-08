"""
SignBridge AI — FastAPI application entry point.

Serves:
  - /health          → liveness probe
  - /static/…        → frontend assets (HTML/CSS/JS)
  - /outputs/…       → generated ISL video files
  - /                → index.html
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routes.health import router as health_router

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent          # project root
FRONTEND_DIR = BASE_DIR / "frontend"
OUTPUTS_DIR = BASE_DIR / "outputs"

# Ensure outputs directory exists at startup
OUTPUTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SignBridge AI",
    description="Converts pre-recorded English audio/video to ISL signed video.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health_router)

# ---------------------------------------------------------------------------
# Static mounts
#
# Order matters: mount /outputs and /static BEFORE the catch-all FileResponse
# so FastAPI resolves them first.
# ---------------------------------------------------------------------------

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------------------------------------------------------------------
# Root — serve index.html
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))
