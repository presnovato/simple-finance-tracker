import type { ReactNode } from 'react'
import { TKButton, TKEmptyState, TKNoticeBar, TKSpinner } from 'tg-mini-app-uikit'

/** Единый контракт состояний экранов: загрузка, ошибка, пусто (spec 07). */

export function PageLoading({ label = 'Загружаю' }: { label?: string }) {
  return (
    <div className="page-state">
      <TKSpinner label={label} />
    </div>
  )
}

export function PageError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="page-state page-state--error">
      <TKNoticeBar tone="red">{message}</TKNoticeBar>
      {onRetry && (
        <TKButton variant="tonal" onClick={onRetry}>Повторить</TKButton>
      )}
    </div>
  )
}

export function PageEmpty({
  title,
  text,
  cta,
  onCta,
}: {
  title: ReactNode
  text?: ReactNode
  cta?: ReactNode
  onCta?: () => void
}) {
  return (
    <div className="page-state">
      <TKEmptyState title={title} text={text} cta={cta} onCta={onCta} />
    </div>
  )
}
