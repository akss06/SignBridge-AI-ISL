import type { Topic, TopicQuestions } from '../types/quiz';

export async function listTopics(): Promise<Topic[]> {
  const res = await fetch('/quiz/topics');
  return (await res.json()) as Topic[];
}

export async function getTopicQuestions(topicId: string): Promise<TopicQuestions> {
  const res = await fetch(`/quiz/topics/${topicId}`);
  return (await res.json()) as TopicQuestions;
}

export function clipUrl(phrase: string): string {
  return `/quiz/clips/${encodeURIComponent(phrase)}`;
}
