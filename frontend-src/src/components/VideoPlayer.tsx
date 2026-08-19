import { forwardRef, useEffect, useRef, useState } from 'react';

interface Props {
  src: string;
  autoPlay?: boolean;
  muted?: boolean;
  loop?: boolean;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
  return `${m}:${s}`;
}

/** Shared custom-chrome video player used by both the pipeline result clip
 *  and the quiz sign clips — replaces native controls with a themed bar. */
export const VideoPlayer = forwardRef<HTMLVideoElement, Props>(function VideoPlayer(
  { src, autoPlay, muted, loop },
  forwardedRef
) {
  const innerRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    if (typeof forwardedRef === 'function') forwardedRef(innerRef.current);
    else if (forwardedRef) forwardedRef.current = innerRef.current;
  }, [forwardedRef]);

  function video() {
    return innerRef.current;
  }

  function togglePlay() {
    const v = video();
    if (!v) return;
    if (v.paused) v.play().catch(() => {});
    else v.pause();
  }

  function replay() {
    const v = video();
    if (!v) return;
    v.currentTime = 0;
    v.play().catch(() => {});
  }

  function seek(e: React.ChangeEvent<HTMLInputElement>) {
    const v = video();
    if (!v) return;
    v.currentTime = Number(e.target.value);
  }

  return (
    <div className="video-player">
      <video
        ref={innerRef}
        src={src}
        autoPlay={autoPlay}
        muted={muted}
        loop={loop}
        playsInline
        onClick={togglePlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
      >
        Your browser does not support video playback.
      </video>

      <div className="video-controls">
        <button className="video-btn" type="button" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❙❙' : '▶'}
        </button>
        <input
          className="video-seek"
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={current}
          onChange={seek}
          aria-label="Seek"
        />
        <span className="video-time">
          {formatTime(current)} / {formatTime(duration)}
        </span>
        <button className="video-btn" type="button" onClick={replay} aria-label="Replay from start">
          ↻
        </button>
      </div>
    </div>
  );
});
