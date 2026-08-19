interface Props {
  score: number;
  total: number;
  onRestart: () => void;
}

export function SummaryView({ score, total, onRestart }: Props) {
  return (
    <section className="panel">
      <h2>Topic complete</h2>
      <p>
        You scored {score} / {total}.
      </p>
      <button className="next-btn" onClick={onRestart}>
        Choose another topic
      </button>
    </section>
  );
}
