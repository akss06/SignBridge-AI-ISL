import { useEffect, useState } from 'react';
import { listTopics } from '../api/quiz';
import type { Topic } from '../types/quiz';

interface Props {
  onSelect: (topicId: string) => void;
}

export function TopicSelect({ onSelect }: Props) {
  const [topics, setTopics] = useState<Topic[]>([]);

  useEffect(() => {
    listTopics().then(setTopics);
  }, []);

  return (
    <section className="panel">
      <h2>Choose a topic</h2>
      <div className="topic-list">
        {topics.map((t) => (
          <button key={t.id} className="topic-btn" onClick={() => onSelect(t.id)}>
            {t.name} ({t.question_count} questions)
          </button>
        ))}
      </div>
    </section>
  );
}
