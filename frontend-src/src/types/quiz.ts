export interface Topic {
  id: string;
  name: string;
  question_count: number;
}

export interface Question {
  clip_phrase: string;
  options: string[];
  correct_answer: string;
}

export interface TopicQuestions {
  topic_id: string;
  questions: Question[];
}
