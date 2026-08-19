import { useEffect, useRef, useState } from 'react';
import { clipUrl } from '../api/quiz';
import type { Question } from '../types/quiz';

interface Props {
  question: Question;
  index: number;
  total: number;
  score: number;
  onAnswered: (correct: boolean) => void;
  onNext: () => void;
}

export function QuestionView({ question, index, total, score, onAnswered, onNext }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [answered, setAnswered] = useState(false);
  const [wasCorrect, setWasCorrect] = useState(false);

  // Reset per-question state and autoplay the new clip, mirroring the
  // original's renderQuestion() re-running on every currentIndex change.
  useEffect(() => {
    setSelected(null);
    setAnswered(false);
    setWasCorrect(false);
    const v = videoRef.current;
    if (v) {
      v.load();
      v.play().catch(() => {});
    }
  }, [question]);

  function handleSelect(opt: string) {
    if (answered) return;
    const correct = opt === question.correct_answer;
    setSelected(opt);
    setAnswered(true);
    setWasCorrect(correct);
    onAnswered(correct);
  }

  function handleReplay() {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = 0;
    v.play().catch(() => {});
  }

  return (
    <section className="panel">
      <div className="quiz-progress">
        <span>
          Question {index + 1} / {total}
        </span>
        <span>
          Score: {score} / {total}
        </span>
      </div>

      <video ref={videoRef} className="clip-video" autoPlay muted playsInline src={clipUrl(question.clip_phrase)}>
        Your browser does not support video playback.
      </video>
      <button className="replay-btn" type="button" onClick={handleReplay}>
        ↻ Replay clip
      </button>

      <div className="options-grid">
        {question.options.map((opt) => {
          let cls = 'option-btn';
          if (answered) {
            if (opt === question.correct_answer) cls += ' correct';
            else if (opt === selected) cls += ' incorrect';
          }
          return (
            <button key={opt} className={cls} disabled={answered} onClick={() => handleSelect(opt)}>
              {opt}
            </button>
          );
        })}
      </div>

      <div className={`feedback ${answered ? (wasCorrect ? 'correct' : 'incorrect') : ''}`}>
        {answered && (wasCorrect ? 'Correct!' : `Incorrect — correct answer: ${question.correct_answer}`)}
      </div>

      <button className={`next-btn ${answered ? '' : 'hidden'}`} onClick={onNext}>
        Next
      </button>
    </section>
  );
}
