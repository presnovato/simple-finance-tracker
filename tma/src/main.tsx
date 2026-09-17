import { Component, StrictMode, type ErrorInfo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './styles.css'
import 'tg-mini-app-uikit/style.css'
import { initTelegram } from './telegram'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('TMA render failed', error, info)
  }

  render(): ReactNode {
    if (this.state.error) {
      return <div className="page-state error" role="alert">Что-то сломалось: {this.state.error.message}</div>
    }

    return this.props.children
  }
}

try {
  initTelegram()
} catch (error) {
  console.warn('Telegram WebApp initialization failed', error)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary><App /></ErrorBoundary>
  </StrictMode>,
)
