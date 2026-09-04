import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { useEffect } from 'react';
import { VideoPlayer } from '../components/VideoPlayer';
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

function CoveragePct({ pct }: { pct: number }) {
  const value = useMotionValue(0);
  const spring = useSpring(value, { stiffness: 90, damping: 20 });
  const rounded = useTransform(spring, (v) => `${Math.round(v)}%`);

  useEffect(() => {
    value.set(pct);
  }, [pct, value]);

  return <motion.span className="coverage-pct">{rounded}</motion.span>;
}

const chipContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.035 } },
};

const chipItem = {
  hidden: { opacity: 0, y: 6, scale: 0.92 },
  show: { opacity: 1, y: 0, scale: 1 },
};

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
      {result.output_video_url && <VideoPlayer src={result.output_video_url} />}

      <div className="coverage-row">
        <span className="coverage-label">Sign coverage</span>
        <div className="coverage-bar-track">
          <motion.div
            className={`coverage-bar-fill ${coverageClass(pct)}`}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ type: 'spring', stiffness: 90, damping: 20 }}
          />
        </div>
        <CoveragePct pct={pct} />
      </div>

      <div className="section-label">ISL Gloss</div>
      <div className="gloss-area">
        {result.sentences.map((sent, i) => (
          <motion.div
            className="gloss-sentence"
            key={i}
            variants={chipContainer}
            initial="hidden"
            animate="show"
          >
            {sent.gloss_tokens.map((tok, j) => (
              <motion.span
                key={j}
                variants={chipItem}
                className={`gloss-chip ${tok.matched ? 'chip-matched' : 'chip-dropped'}`}
                title={tok.matched ? 'Sign found in CISLR' : 'No sign found — dropped'}
              >
                {tok.token}
              </motion.span>
            ))}
          </motion.div>
        ))}
      </div>

      <div className="section-label">Transcript</div>
      <div className="transcript-box">{result.transcript ?? ''}</div>
    </div>
  );
}
