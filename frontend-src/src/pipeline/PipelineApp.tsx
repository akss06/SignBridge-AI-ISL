import { useEffect, useState } from 'react';
import { HealthStatus } from './HealthStatus';
import { FileDropZone } from './FileDropZone';
import { Recorder } from './Recorder';
import { LoadingPanel } from './LoadingPanel';
import { ResultsView } from './ResultsView';
import { useRecorder } from '../hooks/useRecorder';
import { runPipeline, PipelineHttpError } from '../api/pipeline';
import type { PipelineResult } from '../types/pipeline';

export function PipelineApp() {
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const recorder = useRecorder();

  const [loading, setLoading] = useState(false);
  const [requestComplete, setRequestComplete] = useState(false);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [httpErrorMessage, setHttpErrorMessage] = useState<string | null>(null);

  // A finished recording supersedes any previously picked file — mirrors the
  // original clearing fileInput.value/fileNameDisplay inside the recorder's
  // own 'stop' success path.
  useEffect(() => {
    if (recorder.recordedFile) setPickedFile(null);
  }, [recorder.recordedFile]);

  function handleFileSelected(file: File) {
    recorder.supersedeByFile();
    setPickedFile(file);
  }

  // Mirrors the original's exact disabled logic: submit needs something
  // submittable, AND is force-disabled while actively recording (even if a
  // file was already picked earlier — that's the original's own behavior).
  const hasSubmittable = !!(recorder.recordedFile || pickedFile);
  const submitDisabled = !hasSubmittable || loading || recorder.state === 'recording';

  async function handleSubmit() {
    const file = recorder.recordedFile || pickedFile;
    if (!file) return;

    setLoading(true);
    setRequestComplete(false);
    setResult(null);
    setHttpErrorMessage(null);

    try {
      const data = await runPipeline(file);
      setRequestComplete(true);
      setResult(data);
    } catch (err) {
      setRequestComplete(true);
      if (err instanceof PipelineHttpError) {
        setHttpErrorMessage(err.message);
      } else {
        setHttpErrorMessage(`Network error: ${(err as Error).message}`);
      }
    } finally {
      setLoading(false);
    }
  }

  const showLoading = loading;
  const showResults = !loading && (result !== null || httpErrorMessage !== null);

  return (
    <>
      <header className="app-header">
        <div className="header-inner">
          <span className="logo-mark">◈</span>
          <h1 className="app-title">
            SignBridge <span className="accent">AI</span>
          </h1>
          <p className="app-tagline">English audio / video → Indian Sign Language</p>
          <a className="nav-link" href="/quiz.html">
            Quiz mode →
          </a>
        </div>
      </header>

      <main className="app-main">
        <div className="left-col">
          <section className="card upload-card">
            <h2 className="card-title">Upload or record audio</h2>
            <p className="card-hint">
              Accepts <strong>.wav</strong>, <strong>.mp3</strong>, or <strong>.mp4</strong> — audio
              track extracted automatically from video. Or record directly from your microphone below.
            </p>

            <FileDropZone file={pickedFile} onFileSelected={handleFileSelected} />

            <div className="input-divider">
              <span>or</span>
            </div>

            <Recorder recorder={recorder} disabled={loading} />

            <button className="btn btn-primary" disabled={submitDisabled} onClick={handleSubmit}>
              Convert to ISL
            </button>
          </section>

          <HealthStatus />

          {showLoading && <LoadingPanel active={showLoading} complete={requestComplete} />}
        </div>

        <div className="right-col">
          {showResults && <ResultsView result={result} httpErrorMessage={httpErrorMessage} />}
        </div>
      </main>

      <footer className="app-footer">SignBridge AI — ISL Pipeline Demo</footer>
    </>
  );
}
