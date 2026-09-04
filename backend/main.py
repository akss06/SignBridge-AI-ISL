"""
SignBridge AI — FastAPI application entry point.

Serves:
  - /health          → liveness probe
  - /pipeline/run    → full ASR → gloss → lookup → assembly pipeline
  - /quiz/…          → quiz mode API
  - /static/…        → built React frontend assets (frontend-src/dist)
  - /outputs/…       → generated ISL video files
  - /                → the React app's index.html
  - /quiz.html       → the React app's quiz page
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env early — before any service module reads os.getenv()
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.routes.health import router as health_router
from backend.routes.pipeline import router as pipeline_router
from backend.routes.quiz import router as quiz_router
from backend.services.output_cleanup import cleanup_old_outputs

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent          # project root
FRONTEND_DIST = BASE_DIR / "frontend-src" / "dist"         # `npm run build` output
OUTPUTS_DIR = BASE_DIR / "outputs"

# Ensure outputs directory exists at startup
OUTPUTS_DIR.mkdir(exist_ok=True)

# Shown at / and /quiz.html when the React app hasn't been built yet, instead
# of a bare 404 — tells you exactly how to produce the assets.
_NOT_BUILT_HTML = """<!doctype html>
<html><body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.6">
<h1>SignBridge AI — frontend not built</h1>
<p>The React frontend hasn't been built yet. From <code>frontend-src/</code>:</p>
<pre>npm install
npm run build</pre>
<p>then restart this server and reload. For development with hot-reload, run
<code>npm run dev</code> in <code>frontend-src/</code> instead and open the URL it prints
(it proxies the API to this backend).</p>
</body></html>"""

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once per process start, not per request — never touches a video
    # still being generated or one created earlier in this same run, since
    # cleanup_old_outputs() only deletes files whose mtime is already older
    # than the retention threshold.
    cleanup_old_outputs()
    yield


app = FastAPI(
    title="SignBridge AI",
    description="Converts pre-recorded English audio/video to ISL signed video.",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health_router)
app.include_router(pipeline_router)
app.include_router(quiz_router)

# ---------------------------------------------------------------------------
# Static mounts
#
# Order matters: mount /outputs and /static BEFORE the catch-all page routes
# so FastAPI resolves them first. /static is mounted only when the build
# exists — otherwise the page routes below return the "not built" message.
# ---------------------------------------------------------------------------

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

if FRONTEND_DIST.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")


# ---------------------------------------------------------------------------
# Frontend pages
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index():
    idx = FRONTEND_DIST / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return HTMLResponse(_NOT_BUILT_HTML, status_code=503)


@app.get("/quiz.html", include_in_schema=False)
async def quiz_page():
    page = FRONTEND_DIST / "quiz.html"
    if page.exists():
        return FileResponse(str(page))
    return HTMLResponse(_NOT_BUILT_HTML, status_code=503)
