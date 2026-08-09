// SignBridge AI — Quiz mode frontend logic

const topicSelectEl = document.getElementById("topic-select");
const topicListEl = document.getElementById("topic-list");
const questionViewEl = document.getElementById("question-view");
const summaryViewEl = document.getElementById("summary-view");

const clipVideoEl = document.getElementById("clip-video");
const optionsEl = document.getElementById("options");
const feedbackEl = document.getElementById("feedback");
const nextBtnEl = document.getElementById("next-btn");
const questionCounterEl = document.getElementById("question-counter");
const scoreCounterEl = document.getElementById("score-counter");
const summaryTextEl = document.getElementById("summary-text");
const restartBtnEl = document.getElementById("restart-btn");

let questions = [];
let currentIndex = 0;
let score = 0;

function showView(el) {
  [topicSelectEl, questionViewEl, summaryViewEl].forEach((v) => v.classList.add("hidden"));
  el.classList.remove("hidden");
}

async function loadTopics() {
  const res = await fetch("/quiz/topics");
  const topics = await res.json();
  topicListEl.innerHTML = "";
  topics.forEach((t) => {
    const btn = document.createElement("button");
    btn.className = "topic-btn";
    btn.textContent = `${t.name} (${t.question_count} questions)`;
    btn.addEventListener("click", () => startTopic(t.id));
    topicListEl.appendChild(btn);
  });
}

async function startTopic(topicId) {
  const res = await fetch(`/quiz/topics/${topicId}`);
  const data = await res.json();
  questions = data.questions;
  currentIndex = 0;
  score = 0;
  showView(questionViewEl);
  renderQuestion();
}

function renderQuestion() {
  const q = questions[currentIndex];
  clipVideoEl.src = `/quiz/clips/${encodeURIComponent(q.clip_phrase)}`;
  clipVideoEl.load();
  clipVideoEl.play().catch(() => {});

  questionCounterEl.textContent = `Question ${currentIndex + 1} / ${questions.length}`;
  scoreCounterEl.textContent = `Score: ${score} / ${questions.length}`;

  feedbackEl.textContent = "";
  feedbackEl.className = "feedback";
  nextBtnEl.classList.add("hidden");

  optionsEl.innerHTML = "";
  q.options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "option-btn";
    btn.textContent = opt;
    btn.addEventListener("click", () => selectAnswer(opt, btn));
    optionsEl.appendChild(btn);
  });
}

function selectAnswer(selected, clickedBtn) {
  const q = questions[currentIndex];
  const isCorrect = selected === q.correct_answer;

  [...optionsEl.children].forEach((btn) => {
    btn.disabled = true;
    if (btn.textContent === q.correct_answer) btn.classList.add("correct");
    else if (btn === clickedBtn) btn.classList.add("incorrect");
  });

  if (isCorrect) {
    score += 1;
    feedbackEl.textContent = "Correct!";
    feedbackEl.classList.add("correct");
  } else {
    feedbackEl.textContent = `Incorrect — correct answer: ${q.correct_answer}`;
    feedbackEl.classList.add("incorrect");
  }

  scoreCounterEl.textContent = `Score: ${score} / ${questions.length}`;
  nextBtnEl.classList.remove("hidden");
}

nextBtnEl.addEventListener("click", () => {
  currentIndex += 1;
  if (currentIndex >= questions.length) {
    showSummary();
  } else {
    renderQuestion();
  }
});

function showSummary() {
  summaryTextEl.textContent = `You scored ${score} / ${questions.length}.`;
  showView(summaryViewEl);
}

restartBtnEl.addEventListener("click", () => {
  showView(topicSelectEl);
});

loadTopics();
