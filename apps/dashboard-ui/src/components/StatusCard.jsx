function StatusCard({ label, value, tone = "neutral" }) {
  return (
    <article className="summary-card status-card">
      <p className="summary-card__label">{label}</p>
      <p className={`summary-card__value tone-${tone}`}>{value}</p>
    </article>
  );
}

export default StatusCard;
