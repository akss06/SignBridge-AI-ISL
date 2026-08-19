import { useEffect, useState } from 'react';

const STEP_ORDER = ['asr', 'gloss', 'lookup', 'assembly'] as const;
type StepKey = (typeof STEP_ORDER)[number];

const STEP_LABELS: Record<StepKey, string> = {
  asr: 'Transcribing audio…',
  gloss: 'Generating ISL gloss…',
  lookup: 'Matching clips…',
  assembly: 'Assembling video…',
};

// Rough timing — ASR is slowest. Matches the original app.js delays exactly.
const STEP_DELAYS: Record<StepKey, number> = { asr: 0, gloss: 3000, lookup: 6000, assembly: 9000 };

type StepStatus = 'pending' | 'active' | 'done';

interface Props {
  active: boolean;
  /** True once the /pipeline/run response has arrived — flips every step to
   *  "done" immediately, same as the original not waiting out the full
   *  9s staged animation when the real request finishes sooner. */
  complete: boolean;
}

const ALL_DONE: Record<StepKey, StepStatus> = { asr: 'done', gloss: 'done', lookup: 'done', assembly: 'done' };
const ALL_PENDING: Record<StepKey, StepStatus> = { asr: 'pending', gloss: 'pending', lookup: 'pending', assembly: 'pending' };

export function LoadingPanel({ active, complete }: Props) {
  const [statuses, setStatuses] = useState<Record<StepKey, StepStatus>>(ALL_PENDING);

  useEffect(() => {
    if (!active) {
      setStatuses(ALL_PENDING);
      return;
    }

    const timers = STEP_ORDER.map((key, i) =>
      window.setTimeout(() => {
        setStatuses((prev) => {
          const next = { ...prev };
          if (i > 0) next[STEP_ORDER[i - 1]] = 'done';
          next[key] = 'active';
          return next;
        });
      }, STEP_DELAYS[key])
    );

    return () => timers.forEach((t) => clearTimeout(t));
  }, [active]);

  useEffect(() => {
    if (active && complete) setStatuses(ALL_DONE);
  }, [active, complete]);

  if (!active) return null;

  return (
    <div className="loading-panel">
      <div className="spinner" />
      <div className="loading-stages">
        {STEP_ORDER.map((key) => (
          <span key={key} className={`stage-step ${statuses[key]}`}>
            {STEP_LABELS[key]}
          </span>
        ))}
      </div>
    </div>
  );
}
