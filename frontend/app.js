/**
 * SignBridge AI — frontend (Stage 6)
 *
 * Responsibilities:
 *   1. Health check on load.
 *   2. File input + drag-and-drop wiring.
 *   3. POST /pipeline/run with the uploaded file.
 *   4. Animate a simple loading state while processing.
 *   5. Render results: video player, coverage bar, gloss chips, transcript.
 *   6. Handle 0%-coverage and error states gracefully.
 */

// ── DOM refs ─────────────────────────────────────────────────────────────────

const healthDot       = document.getElementById('health-dot');
const healthLabel     = document.getElementById('health-label');
const fileInput       = document.getElementById('file-input');
const fileDrop        = document.getElementById('file-drop');
const fileNameDisplay = document.getElementById('file-name-display');
const submitBtn       = document.getElementById('submit-btn');
const loadingPanel    = document.getElementById('loading-panel');
const resultsCard     = document.getElementById('results-card');
const noCoverageCard  = document.getElementById('no-coverage-card');
const errorCard       = document.getElementById('error-card');
const errorMessage    = document.getElementById('error-message');
const islVideo        = document.getElementById('isl-video');
const coverageFill    = document.getElementById('coverage-fill');
const coveragePct     = document.getElementById('coverage-pct');
const glossArea       = document.getElementById('gloss-area');
const transcriptBox   = document.getElementById('transcript-box');
const noCovTranscript = document.getElementById('no-coverage-transcript');

// Loading step elements
const steps = {
  asr:      document.getElementById('step-asr'),
  gloss:    document.getElementById('step-gloss'),
  lookup:   document.getElementById('step-lookup'),
  assembly: document.getElementById('step-assembly'),
};


// ── Health check ─────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const res  = await fetch('/health');
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      healthDot.classList.add('ok');
      healthLabel.textContent = `${data.service} v${data.version} — service OK`;
    } else {
      throw new Error(data.status ?? 'unexpected response');
    }
  } catch (err) {
    healthDot.classList.add('error');
    healthLabel.textContent = `Service unreachable: ${err.message}`;
  }
}

checkHealth();


// ── File input wiring ─────────────────────────────────────────────────────────

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (file) {
    fileNameDisplay.textContent = file.name;
    submitBtn.disabled = false;
  } else {
    fileNameDisplay.textContent = 'No file selected';
    submitBtn.disabled = true;
  }
});

fileDrop.addEventListener('dragover',  (e) => { e.preventDefault(); fileDrop.style.borderColor = '#f59e0b'; });
fileDrop.addEventListener('dragleave', ()  => { fileDrop.style.borderColor = ''; });
fileDrop.addEventListener('drop', (e) => {
  e.preventDefault();
  fileDrop.style.borderColor = '';
  const file = e.dataTransfer?.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event('change'));
  }
});


// ── UI state helpers ──────────────────────────────────────────────────────────

function hideAllResults() {
  resultsCard.classList.add('hidden');
  noCoverageCard.classList.add('hidden');
  errorCard.classList.add('hidden');
}

function setLoading(active) {
  if (active) {
    loadingPanel.classList.remove('hidden');
    submitBtn.disabled = true;
    hideAllResults();
    // Reset all step indicators
    Object.values(steps).forEach(el => el.classList.remove('active', 'done'));
  } else {
    loadingPanel.classList.add('hidden');
    submitBtn.disabled = false;
  }
}

// Cycle through loading step labels with a small delay so the user
// sees progress even though it's one HTTP call.
function animateLoadingSteps() {
  const order = ['asr', 'gloss', 'lookup', 'assembly'];
  const delays = [0, 3000, 6000, 9000];   // rough timing — ASR is slowest
  order.forEach((key, i) => {
    setTimeout(() => {
      // Mark previous step done
      if (i > 0) steps[order[i - 1]].classList.replace('active', 'done');
      steps[key].classList.add('active');
    }, delays[i]);
  });
}


// ── Render results ────────────────────────────────────────────────────────────

function renderResults(data) {
  hideAllResults();

  // Error state (pipeline-level error, not HTTP error)
  if (data.error && !data.output_video_url) {
    // Distinguish 0% coverage from a real crash
    if (data.coverage === 0) {
      noCovTranscript.textContent = data.transcript || '';
      noCoverageCard.classList.remove('hidden');
    } else {
      errorMessage.textContent = data.error;
      errorCard.classList.remove('hidden');
    }
    return;
  }

  // Normal results
  resultsCard.classList.remove('hidden');

  // Video
  islVideo.src = data.output_video_url;
  islVideo.load();

  // Coverage bar
  const pct = Math.round((data.coverage ?? 0) * 100);
  coverageFill.style.width = pct + '%';
  coveragePct.textContent  = pct + '%';
  // Colour the fill: green ≥70%, amber 40–69%, red <40%
  coverageFill.className = 'coverage-bar-fill ' +
    (pct >= 70 ? 'cov-high' : pct >= 40 ? 'cov-mid' : 'cov-low');

  // Gloss chips — one row per sentence, chips per token
  glossArea.innerHTML = '';
  (data.sentences ?? []).forEach(sent => {
    const row = document.createElement('div');
    row.className = 'gloss-sentence';
    sent.gloss_tokens.forEach(tok => {
      const chip = document.createElement('span');
      chip.className = 'gloss-chip ' + (tok.matched ? 'chip-matched' : 'chip-dropped');
      chip.textContent = tok.token;
      chip.title = tok.matched ? 'Sign found in CISLR' : 'No sign found — dropped';
      row.appendChild(chip);
    });
    glossArea.appendChild(row);
  });

  // Transcript
  transcriptBox.textContent = data.transcript ?? '';
}


// ── Submit handler ────────────────────────────────────────────────────────────

submitBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) return;

  setLoading(true);
  animateLoadingSteps();

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/pipeline/run', {
      method: 'POST',
      body: formData,
    });

    // Mark all steps done
    Object.values(steps).forEach(el => { el.classList.remove('active'); el.classList.add('done'); });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      hideAllResults();
      errorMessage.textContent = err.detail ?? `Server error ${res.status}`;
      errorCard.classList.remove('hidden');
      return;
    }

    const data = await res.json();
    renderResults(data);

  } catch (err) {
    hideAllResults();
    errorMessage.textContent = `Network error: ${err.message}`;
    errorCard.classList.remove('hidden');
  } finally {
    setLoading(false);
  }
});
