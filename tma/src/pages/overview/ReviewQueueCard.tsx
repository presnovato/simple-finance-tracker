import { TKButton, TKCard } from 'tg-mini-app-uikit'

export function ReviewQueueCard({ count, onOpen }: { count: number; onOpen: () => void }) {
  if (!count) return null
  return (
    <TKCard className="overview-review-card">
      <div className="chart-heading">
        <div>
          <span className="eyebrow">Проверка</span>
          <h2>На ожидании проверки: {count}</h2>
        </div>
        <TKButton size="sm" variant="tonal" onClick={onOpen}>Открыть</TKButton>
      </div>
    </TKCard>
  )
}
