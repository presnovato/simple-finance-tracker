const DEV_INIT_DATA_KEY = 'finance-dev-init-data'

export function initTelegram(): void {
  const webApp = window.Telegram?.WebApp

  try {
    webApp?.ready?.()
  } catch (error) {
    console.warn('Telegram WebApp ready() failed', error)
  }

  try {
    webApp?.expand?.()
  } catch (error) {
    console.warn('Telegram WebApp expand() failed', error)
  }

  try {
    webApp?.setHeaderColor?.('#0b0d12')
  } catch (error) {
    console.warn('Telegram WebApp setHeaderColor() failed', error)
  }

  try {
    webApp?.setBackgroundColor?.('#0b0d12')
  } catch (error) {
    console.warn('Telegram WebApp setBackgroundColor() failed', error)
  }

  const params = new URLSearchParams(window.location.search)
  const devInitData = params.get('initData')
  if (devInitData) {
    sessionStorage.setItem(DEV_INIT_DATA_KEY, devInitData)
    params.delete('initData')
    const query = params.toString()
    window.history.replaceState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
  }
}

export function telegramInitData(): string {
  return window.Telegram?.WebApp?.initData || sessionStorage.getItem(DEV_INIT_DATA_KEY) || ''
}

export function haptic(kind: 'light' | 'medium' = 'light'): void {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(kind)
  } catch (error) {
    console.warn('Telegram WebApp haptic feedback failed', error)
  }
}
