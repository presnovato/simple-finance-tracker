import { useState } from 'react'
import { TKButton, TKCard, TKIcon, TKIconButton, TKProgress } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { BudgetResponse } from '../../types'
import { budgetRemainingLabel, budgetStatusColor, progressValue } from './overviewHelpers'

export function BudgetCard({
  budget,
  onConfigure,
}: {
  budget: BudgetResponse
  onConfigure: () => void
}) {
  const overall = budget.overall
  const categories = budget.categories || []
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  const hasCategories = categories.length > 0

  function toggleCategories() {
    if (hasCategories) setCategoriesOpen((value) => !value)
  }

  return (
    <TKCard className="overview-budget-card">
      <div className="budget-heading">
        <div>
          <span className="eyebrow">Недельный бюджет</span>
          <h2>Лимиты расходов</h2>
          <span className="budget-week-label">
            {formatDay(budget.week_start)} — {formatDay(budget.week_end)}
          </span>
        </div>
        {budget.is_current && (
          <TKIconButton
            size="md"
            variant="surface"
            icon="edit"
            label="Настроить бюджет"
            onClick={onConfigure}
          />
        )}
      </div>

      {!budget.configured ? (
        <div className="budget-empty">
          <p>Бюджет ещё не создан. Задай общий недельный лимит; категории и их лимиты можно добавить по желанию.</p>
          {budget.is_current && <TKButton variant="filled" onClick={onConfigure}>Настроить бюджет</TKButton>}
        </div>
      ) : (
        <>
          {overall ? (
            <div
              className={`budget-overall budget-status-${overall.status}${hasCategories ? ' budget-overall-clickable' : ''}`}
              role={hasCategories ? 'button' : undefined}
              tabIndex={hasCategories ? 0 : undefined}
              aria-expanded={hasCategories ? categoriesOpen : undefined}
              aria-controls={hasCategories ? 'budget-category-list' : undefined}
              onClick={hasCategories ? toggleCategories : undefined}
              onKeyDown={hasCategories ? (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  toggleCategories()
                }
              } : undefined}
            >
              <div className="budget-value-row budget-overall-main">
                <span className="budget-overall-label">Остаток</span>
                <span className="budget-overall-value">
                  <strong>{formatMoney(overall.spent)} из {formatMoney(overall.limit)}</strong>
                  {hasCategories && (
                    <TKIcon
                      name="chevronDown"
                      size={18}
                      strokeWidth={2.2}
                      className={`disclosure-icon${categoriesOpen ? ' is-open' : ''}`}
                    />
                  )}
                </span>
              </div>
              <TKProgress
                value={progressValue(overall.percent)}
                label={`Общий бюджет: ${overall.percent}%`}
                size="sm"
              />
            </div>
          ) : (
            <div className="budget-category-only">
              <span>Общий лимит не задан</span>
              <strong>{formatMoney(budget.selected_spent || '0')}</strong>
            </div>
          )}

          {categoriesOpen && (
            <div id="budget-category-list" className="budget-category-list">
              {categories.map((category) => (
                <div className="budget-category-row" key={category.category}>
                  <div className="budget-value-row">
                    <span>{category.category}</span>
                    <strong>
                      {category.limit
                        ? `${formatMoney(category.spent)} из ${formatMoney(category.limit)}`
                        : `${formatMoney(category.spent)} · без отдельного лимита`}
                    </strong>
                  </div>
                  {category.limit ? (
                    <>
                      <div className="budget-value-row budget-subvalue">
                        <span>{category.percent}%</span>
                        <strong>{budgetRemainingLabel(category.remaining)}</strong>
                      </div>
                      <TKProgress
                        value={progressValue(category.percent)}
                        label={`${category.category}: ${category.percent}%`}
                        size="sm"
                        style={{
                          ['--tk-accent' as string]: budgetStatusColor(category.status),
                          ['--tk-accent-grad' as string]: budgetStatusColor(category.status),
                        }}
                      />
                    </>
                  ) : (
                    <div className="budget-value-row budget-subvalue">
                      <span>Отдельный лимит не задан</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </TKCard>
  )
}
