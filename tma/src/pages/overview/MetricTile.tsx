export function MetricTile({
  label,
  value,
  className = '',
  note,
}: {
  label: string
  value: string
  className?: string
  note?: string
}) {
  return (
    <div className={`metric-tile ${className}`.trim()}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {note && <span className="metric-note">{note}</span>}
    </div>
  )
}
