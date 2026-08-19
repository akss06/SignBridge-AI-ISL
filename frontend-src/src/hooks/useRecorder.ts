import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Ports the recording state machine from the original frontend/app.js 1:1,
 * including edge cases found and fixed during that build:
 *   - capability check up front (disables recording, doesn't just fail on click)
 *   - differentiated permission-error messages (denied / no device / device busy)
 *   - minimum recording duration (400ms) rejected client-side
 *   - only mime types the backend's extension allowlist accepts (webm, no ogg)
 *   - cancellation path when a file pick interrupts an in-progress recording,
 *     so the async 'stop' event doesn't resurrect a discarded recording
 *
 * State machine: idle -> recording -> recorded -> (submitted | reRecord -> recording)
 * 'unsupported' is a terminal state when the browser lacks MediaRecorder/getUserMedia.
 */

export type RecorderState = 'unsupported' | 'idle' | 'recording' | 'recorded';

const MIN_RECORDING_MS = 400;

function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm'];
  for (const type of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return type;
  }
  return ''; // let the browser choose its own default (e.g. audio/mp4 on Safari)
}

function extensionForMimeType(mimeType: string): string {
  if (mimeType.includes('mp4')) return 'mp4';
  return 'webm';
}

export interface UseRecorderResult {
  state: RecorderState;
  elapsedSeconds: number;
  errorMessage: string | null;
  recordedFile: File | null;
  audioPreviewUrl: string | null;
  start: () => void;
  stop: () => void;
  reRecord: () => void;
  /** Called when a file is picked elsewhere in the UI — cancels any active
   *  recording and clears any finished one, so only one input method is live. */
  supersedeByFile: () => void;
}

export function useRecorder(): UseRecorderResult {
  const recordingSupported = !!(navigator.mediaDevices && window.MediaRecorder);

  const [state, setState] = useState<RecorderState>(recordingSupported ? 'idle' : 'unsupported');
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(
    recordingSupported ? null : 'Recording is not supported in this browser — use file upload instead.'
  );
  const [recordedFile, setRecordedFile] = useState<File | null>(null);
  const [audioPreviewUrl, setAudioPreviewUrl] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const recordingStartTimeRef = useRef<number | null>(null);
  const timerIntervalRef = useRef<number | null>(null);
  const recordingCancelledRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (timerIntervalRef.current !== null) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    recordingStartTimeRef.current = Date.now();
    setElapsedSeconds(0);
    timerIntervalRef.current = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - recordingStartTimeRef.current!) / 1000));
    }, 250);
  }, []);

  const start = useCallback(async () => {
    setErrorMessage(null);

    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setErrorMessage('Recording is not supported in this browser — use file upload instead.');
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const name = (err as DOMException).name;
      if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        setErrorMessage('No microphone found — use file upload instead.');
      } else if (name === 'NotReadableError' || name === 'TrackStartError') {
        setErrorMessage('Microphone is unavailable (in use by another app?) — use file upload instead.');
      } else {
        setErrorMessage('Microphone access denied. Allow microphone access to record, or use file upload instead.');
      }
      return;
    }

    // Starting a new recording invalidates any previous one.
    setRecordedFile(null);

    const mimeType = pickMimeType();
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    mediaRecorderRef.current = recorder;
    recordedChunksRef.current = [];

    recorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) recordedChunksRef.current.push(e.data);
    });

    recorder.addEventListener('stop', () => {
      stream.getTracks().forEach((track) => track.stop());
      stopTimer();

      if (recordingCancelledRef.current) {
        // A picked file interrupted this recording — discard it, don't
        // finalize/preview it.
        recordingCancelledRef.current = false;
        setState('idle');
        return;
      }

      const elapsedMs = Date.now() - recordingStartTimeRef.current!;
      const finalMimeType = recorder.mimeType || 'audio/webm';
      const blob = new Blob(recordedChunksRef.current, { type: finalMimeType });

      if (blob.size === 0 || elapsedMs < MIN_RECORDING_MS) {
        setErrorMessage('Recording was too short — try again.');
        setState('idle');
        return;
      }

      const ext = extensionForMimeType(finalMimeType);
      const file = new File([blob], `recording.${ext}`, { type: finalMimeType });
      setAudioPreviewUrl(URL.createObjectURL(blob));
      setRecordedFile(file);
      setState('recorded');
    });

    recorder.start();
    setState('recording');
    startTimer();
  }, [startTimer, stopTimer]);

  const stop = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    }
  }, []);

  const reRecord = useCallback(() => {
    setRecordedFile(null);
    setAudioPreviewUrl(null);
    setErrorMessage(null);
    start();
  }, [start]);

  const supersedeByFile = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state === 'recording') {
      recordingCancelledRef.current = true;
      stop();
    }
    setRecordedFile(null);
    setAudioPreviewUrl(null);
    setErrorMessage(null);
    if (recordingSupported) setState('idle');
  }, [stop, recordingSupported]);

  // Clean up the object URL when the component unmounts or a new preview replaces it.
  useEffect(() => {
    return () => {
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
    };
  }, [audioPreviewUrl]);

  return { state, elapsedSeconds, errorMessage, recordedFile, audioPreviewUrl, start, stop, reRecord, supersedeByFile };
}
