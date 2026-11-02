import {
  TKButton,
  TKChip,
  TKNoticeBar,
  TKNativeField,
  TKSheet,
} from 'tg-mini-app-uikit'

import { formatDay } from '../../format'
import type { Categories } from '../../types'

export function HistoryFilterSheets({
  filterOpen,
  periodOpen,
  category,
  categoryNull,
  date,
  needsReview,
  categoryChips,
  periodLabel,
  periodDraft,
  periodError,
  activeFilterCount,
  onCloseFilter,
  onClosePeriod,
  onCategory,
  onToggleCategoryNull,
  onDate,
  onToggleNeedsReview,
  onOpenPeriod,
  onPeriodDraft,
  onApplyPeriod,
  onClearPeriod,
  onClearFilters,
}: {
  filterOpen: boolean
  periodOpen: boolean
  category: string
  categoryNull: boolean
  date: string
  needsReview: boolean
  categoryChips: Array<{ value: string; label: string }>
  periodLabel: string
  periodDraft: { from: string; to: string }
  periodError: string
  activeFilterCount: number
  onCloseFilter: () => void
  onClosePeriod: () => void
  onCategory: (value: string) => void
  onToggleCategoryNull: () => void
  onDate: (value: string) => void
  onToggleNeedsReview: () => void
  onOpenPeriod: () => void
  onPeriodDraft: (draft: { from: string; to: string }) => void
  onApplyPeriod: () => void
  onClearPeriod: () => void
  onClearFilters: () => void
}) {
  return (
    <>
      <TKSheet
        open={filterOpen}
        onClose={onCloseFilter}
        title="Фильтры истории"
      >
        <div className="history-filter-sheet">
          <section className="history-filter-section">
            <div className="history-filter-section-heading">
              <strong>Период</strong>
              <span>{periodLabel || (date ? `День ${formatDay(date)}` : 'Любой')}</span>
            </div>
            <TKButton
              full
              variant="tonal"
              onClick={() => {
                onCloseFilter()
                onOpenPeriod()
              }}
            >
              {periodLabel ? `Изменить: ${periodLabel}` : 'Выбрать период'}
            </TKButton>
            {date && (
              <TKChip selected removable onClick={() => onDate('')} onRemove={() => onDate('')}>
                День · {formatDay(date)}
              </TKChip>
            )}
          </section>

          <section className="history-filter-section">
            <div className="history-filter-section-heading">
              <strong>Категория</strong>
              <span>{[needsReview ? 'На проверке' : null, categoryNull ? 'Без категории' : null, category || null].filter(Boolean).join(' · ') || 'Любая'}</span>
            </div>
            <div className="history-category-options">
              <TKChip selected={needsReview} onClick={onToggleNeedsReview}>
                ⚠ Проверить
              </TKChip>
              <TKChip selected={categoryNull} onClick={onToggleCategoryNull}>
                Без категории
              </TKChip>
              {categoryChips.map((chip) => (
                <TKChip
                  key={chip.value}
                  selected={category === chip.value}
                  onClick={() => onCategory(category === chip.value ? '' : chip.value)}
                >
                  {chip.label}
                </TKChip>
              ))}
            </div>
          </section>

          {activeFilterCount > 0 && (
            <TKButton
              full
              variant="plain"
              onClick={() => {
                onClearFilters()
                onCloseFilter()
              }}
            >
              Сбросить фильтры
            </TKButton>
          )}
        </div>
      </TKSheet>

      <TKSheet
        open={periodOpen}
        onClose={onClosePeriod}
        title="Период истории"
      >
        <div className="history-period-form">
          <div className="history-period-fields">
            <TKNativeField
              type="date"
              label="От"
              value={periodDraft.from}
              onChange={(value) => onPeriodDraft({ ...periodDraft, from: value })}
            />
            <TKNativeField
              type="date"
              label="До"
              value={periodDraft.to}
              onChange={(value) => onPeriodDraft({ ...periodDraft, to: value })}
            />
          </div>
          {periodError && <TKNoticeBar tone="red">{periodError}</TKNoticeBar>}
          <TKButton full variant="filled" onClick={onApplyPeriod}>Применить период</TKButton>
          {(periodDraft.from || periodDraft.to) && (
            <TKButton full variant="plain" onClick={onClearPeriod}>Очистить период</TKButton>
          )}
        </div>
      </TKSheet>
    </>
  )
}
