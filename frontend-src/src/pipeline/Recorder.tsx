import { motion } from 'framer-motion';
import type { UseRecorderResult } from '../hooks/useRecorder';

interface Props {
  recorder: UseRecorderResult;
  disabled: boolean; // true while a submission is in flight
}

function formatElapsed(totalSeconds: number): string {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
  const s = String(totalSeconds % 60).padStart(2, '0');
  return `${m}:${s}`;
}

export function Recorder({ recorder, disabled }: Props) {
  const { state, elapsedSeconds, errorMessage, audioPreviewUrl, start, stop, reRecord } = recorder;

  const recordButtonDisabled = state === 'unsupported' || disabled;

  return (
    <div className="record-section">
      <button
        className={`btn btn-record ${state === 'recording' ? 'recording' : ''}`}
        type="button"
        disabled={recordButtonDisabled}
        onClick={() => (state === 'recording' ? stop() : start())}
      >
        <span className="record-dot" />
        <span>{state === 'recording' ? 'Stop recording' : 'Record audio'}</span>
      </button>

      {state === 'recording' && <span className="record-timer">{formatElapsed(elapsedSeconds)}</span>}

      {state === 'recorded' && audioPreviewUrl && (
        <motion.div
          className="record-preview"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
        >
          <audio controls src={audioPreviewUrl} />
          <button className="btn-link" type="button" disabled={disabled} onClick={reRecord}>
            Re-record
          </button>
        </motion.div>
      )}

      {errorMessage && <p className="record-message">{errorMessage}</p>}
    </div>
  );
}
