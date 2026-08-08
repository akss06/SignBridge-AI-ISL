/**
 * SignBridge AI — frontend JS (Stage 1 skeleton)
 *
 * Stage 1 responsibilities:
 *   1. Hit /health on page load and reflect the result in the UI.
 *   2. Wire the file-input so the submit button enables on file selection.
 *
 * Upload + pipeline wiring is added in Stage 6.
 */

// ── Health check ────────────────────────────────────────────────────────────

const healthDot   = document.getElementById('health-dot');
const healthLabel = document.getElementById('health-label');

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

// ── File input wiring ────────────────────────────────────────────────────────

const fileInput      = document.getElementById('file-input');
const fileDrop       = document.getElementById('file-drop');
const fileNameDisplay = document.getElementById('file-name-display');
const submitBtn      = document.getElementById('submit-btn');

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

// Drag-and-drop onto the label
fileDrop.addEventListener('dragover', (e) => {
  e.preventDefault();
  fileDrop.style.borderColor = '#f59e0b';
});

fileDrop.addEventListener('dragleave', () => {
  fileDrop.style.borderColor = '';
});

fileDrop.addEventListener('drop', (e) => {
  e.preventDefault();
  fileDrop.style.borderColor = '';
  const file = e.dataTransfer?.files[0];
  if (file) {
    // Assign to the input so the change handler fires consistently
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event('change'));
  }
});

// Submit handler — full pipeline wired in Stage 6
submitBtn.addEventListener('click', () => {
  // Placeholder: will be replaced in Stage 6
  console.log('Submit clicked — pipeline wiring coming in Stage 6.');
});
