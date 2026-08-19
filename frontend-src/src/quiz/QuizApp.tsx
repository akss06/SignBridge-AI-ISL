import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { TopicSelect } from './TopicSelect';
import { QuestionView } from './QuestionView';
import { SummaryView } from './SummaryView';
import { getTopicQuestions } from '../api/quiz';
import type { Question } from '../types/quiz';

type View = 'topics' | 'question' | 'summary';

export function QuizApp() {
  const [view, setView] = useState<View>('topics');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [index, setIndex] = useState(0);
  const [score, setScore] = useState(0);

  async function handleSelectTopic(topicId: string) {
    const data = await getTopicQuestions(topicId);
    setQuestions(data.questions);
    setIndex(0);
    setScore(0);
    setView('question');
  }

  function handleAnswered(correct: boolean) {
    if (correct) setScore((s) => s + 1);
  }

  function handleNext() {
    if (index + 1 >= questions.length) {
      setView('summary');
    } else {
      setIndex((i) => i + 1);
    }
  }

  return (
    <>
      <header className="app-header">
        <div className="header-inner">
          <span className="logo-mark">🤟</span>
          <span className="app-title">
            SignBridge <span className="accent">AI</span>
          </span>
          <span className="app-tagline">Quiz mode</span>
          <a className="nav-link" href="/">
            ← Back to converter
          </a>
        </div>
      </header>

      <main className="quiz-main">
        <AnimatePresence mode="wait">
          {view === 'topics' && (
            <motion.div key="topics" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
              <TopicSelect onSelect={handleSelectTopic} />
            </motion.div>
          )}

          {view === 'question' && questions.length > 0 && (
            <motion.div key={`q-${index}`} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }}>
              <QuestionView
                question={questions[index]}
                index={index}
                total={questions.length}
                score={score}
                onAnswered={handleAnswered}
                onNext={handleNext}
              />
            </motion.div>
          )}

          {view === 'summary' && (
            <motion.div key="summary" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
              <SummaryView score={score} total={questions.length} onRestart={() => setView('topics')} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </>
  );
}
