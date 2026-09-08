export function MetricCard({ label, children }) {
  return (
    <article>
      <span>{label}</span>
      <strong>{children}</strong>
    </article>
  );
}
