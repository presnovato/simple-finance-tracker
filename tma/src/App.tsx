import { lazy, Suspense, useEffect, useState } from 'react'
import { TKProvider } from 'tg-mini-app-uikit'
import { getCryptoOverviewVisibility } from './api'
import { isCryptoOverviewVisible, setCryptoOverviewVisible } from './crypto'
import { haptic } from './telegram'
import type { HistoryPreset } from './types'

const ACCENT = '#77e6b6'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const HistoryPage = lazy(() => import('./pages/HistoryPage').then((module) => ({ default: module.HistoryPage })))
const DebtsPage = lazy(() => import('./pages/DebtsPage').then((module) => ({ default: module.DebtsPage })))
const CryptoPage = lazy(() => import('./pages/CryptoPage').then((module) => ({ default: module.CryptoPage })))
const SubscriptionsPage = lazy(() => import('./pages/SubscriptionsPage').then((module) => ({ default: module.SubscriptionsPage })))

type Tab = 'overview' | 'history' | 'debts' | 'crypto' | 'subs'

const tabs: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Обзор' },
  { id: 'history', label: 'История' },
  { id: 'debts', label: 'Долги' },
  { id: 'crypto', label: 'Крипта' },
  { id: 'subs', label: 'Подписки' },
]

function initialTab(): Tab {
  const requested = new URLSearchParams(window.location.search).get('tab')
  return tabs.some((tab) => tab.id === requested) ? requested as Tab : 'overview'
}

export default function App() {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [historyPreset, setHistoryPreset] = useState<HistoryPreset>({})
  const [presetVersion, setPresetVersion] = useState(0)
  const [cryptoVisible, setCryptoVisible] = useState(() => isCryptoOverviewVisible())

  useEffect(() => {
    let active = true
    getCryptoOverviewVisibility()
      .then((result) => {
        if (!active || typeof result.overview_visible !== 'boolean') return
        setCryptoVisible(result.overview_visible)
        setCryptoOverviewVisible(result.overview_visible)
      })
      .catch(() => {})
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!cryptoVisible && tab === 'crypto') setTab('overview')
  }, [cryptoVisible, tab])

  const selectTab = (next: Tab) => {
    if (next === 'crypto' && !cryptoVisible) return
    haptic()
    setTab(next)
  }

  const openHistory = (preset: HistoryPreset) => {
    setHistoryPreset(preset)
    setPresetVersion((value) => value + 1)
    selectTab('history')
  }

  return (
    <TKProvider theme="dark" accent={ACCENT} className="app-shell">
      <div className="app-content">
        <Suspense fallback={<div className="page-state">Открываю раздел…</div>}>
          {tab === 'overview' && (
            <OverviewPage
              openHistory={openHistory}
            />
          )}
          {tab === 'history' && <HistoryPage preset={historyPreset} presetVersion={presetVersion} />}
          {tab === 'debts' && <DebtsPage />}
          {tab === 'crypto' && <CryptoPage onOverviewVisibilityChange={setCryptoVisible} />}
          {tab === 'subs' && <SubscriptionsPage />}
        </Suspense>
      </div>

      <nav className={`bottom-tabs ${cryptoVisible ? '' : 'bottom-tabs--four'}`} aria-label="Разделы приложения">
        {tabs.filter((item) => item.id !== 'crypto' || cryptoVisible).map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? 'active' : ''}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => selectTab(item.id)}
          >
            <TabIcon name={item.id} />
            {item.label}
          </button>
        ))}
      </nav>
    </TKProvider>
  )
}

function TabIcon({ name }: { name: Tab }) {
  if (name === 'overview') {
    return (
      <svg className="tab-icon" viewBox="0 0 20 20" width="20" height="20" fill="currentColor" aria-hidden="true">
        <path d="M2.5 2.5h6v6h-6v-6Zm9 0h6v3.5h-6V2.5Zm0 6.5h6v8.5h-6V9Zm-9 2.5h6v6h-6v-6Z" />
      </svg>
    )
  }
  if (name === 'history') {
    return (
      <svg className="tab-icon" viewBox="0 0 20 20" width="20" height="20" fill="currentColor" aria-hidden="true">
        <path d="M3.5 4a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM7 4.75h10v1.5H7v-1.5ZM3.5 8.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM7 9.25h10v1.5H7v-1.5ZM3.5 13a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM7 13.75h10v1.5H7v-1.5Z" />
      </svg>
    )
  }
  if (name === 'crypto') {
    return (
      <svg className="tab-icon" viewBox="0 0 20 20" width="20" height="20" fill="currentColor" aria-hidden="true">
        <path d="M10 1.5 17 5v10l-7 3.5L3 15V5l7-3.5Zm0 2.2L5.2 6.1 10 8.5l4.8-2.4L10 3.7Zm-5 4.3v5.8l4 2V10L5 8Zm6 7.8 4-2V8l-4 2v5.8Z" />
      </svg>
    )
  }
  if (name === 'subs') {
    return (
      <svg className="tab-icon" viewBox="0 0 20 20" width="20" height="20" fill="currentColor" aria-hidden="true">
        <path d="M10 2.2a2.5 2.5 0 0 1 2.5 2.5v.8h1.8A2.7 2.7 0 0 1 17 8.2v6.1a2.7 2.7 0 0 1-2.7 2.7H5.7A2.7 2.7 0 0 1 3 14.3V8.2a2.7 2.7 0 0 1 2.7-2.7h1.8v-.8A2.5 2.5 0 0 1 10 2.2Zm0 1.7A.8.8 0 0 0 9.2 4.7v.8h1.6v-.8a.8.8 0 0 0-.8-.8ZM6.5 9.1a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm7 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z" />
      </svg>
    )
  }
  return (
    <svg className="tab-icon" viewBox="0 0 20 20" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="m7.6 3.2 1.4 1.4-2.4 2.4H13a4.5 4.5 0 0 1 0 9H8v-2h5a2.5 2.5 0 0 0 0-5H6.6L9 11.4l-1.4 1.4L2.8 8l4.8-4.8Z" />
    </svg>
  )
}
