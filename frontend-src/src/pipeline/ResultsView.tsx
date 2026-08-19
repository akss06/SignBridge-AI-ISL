import type { PipelineResult } from '../types/pipeline';

interface Props {
  result: PipelineResult | null;
  httpErrorMessage: string | null;
}

function coverageClass(pct: number): string {
  if (pct >= 70) return 'cov-high';
  if (pct >= 40) return 'cov-mid';
  return 'cov-low';
}

export function ResultsView({ result, httpErrorMessage }: Props) {
  if (httpErrorMessage) {
    return (
      <div className="card error-card">
        <h2 className="card-title">Something went wrong</h2>
        <p className="error-message">{httpErrorMessage}</p>
      </div>
    );
  }

  if (!result) return null;

  // Pipeline-level error (not an HTTP error) — distinguish 0% coverage from a real crash.
  if (result.error && !result.output_video_url) {
    if (result.coverage === 0) {
      return (
        <div className="card error-card">
          <h2 className="card-title">No signs found</h2>
          <p className="card-hint">
            None of the words in this audio matched signs in the CISLR dataset. Try a sentence with
            common everyday vocabulary.
          </p>
          <div className="transcript-box">{result.transcript || ''}</div>
        </div>
      );
    }
    return (
      <div className="card error-card">
        <h2 className="card-title">Something went wrong</h2>
        <p className="error-message">{result.error}</p>
      </div>
    );
  }

  const pct = Math.round((result.coverage ?? 0) * 100);

  return (
    <div className="card results-card">
      <div className="video-wrapper">
        <video id="isl-video" controls playsInline src={result.output_video_url ?? undefined}>
          Your browser does not support video playback.
        </video>
      </div>

      <div className="coverage-row">
        <span className="coverage-label">Sign coverage</span>
        <div className="coverage-bar-track">
          <div className={`coverage-bar-fill ${coverageClass(pct)}`} style={{ width: `${pct}%` }} />
        </div>
        <span className="coverage-pct">{pct}%</span>
      </div>

      <div className="section-label">ISL Gloss</div>
      <div className="gloss-area">
        {result.sentences.map((sent, i) => (
          <div className="gloss-sentence" key={i}>
            {sent.gloss_tokens.map((tok, j) => (
              <span
                key={j}
                className={`gloss-chip ${tok.matched ? 'chip-matched' : 'chip-dropped'}`}
                title={tok.matched ? 'Sign found in CISLR' : 'No sign found — dropped'}
              >
                {tok.token}
              </span>
            ))}
          </div>
        ))}
      </div>

      <div className="section-label">Transcript</div>
      <div className="transcript-box">{result.transcript ?? ''}</div>
    </div>
  );
}
