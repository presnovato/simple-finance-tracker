const CRYPTO_OVERVIEW_HIDDEN_KEY = 'finance-tracker:tma:v1:crypto-overview-hidden'

export function isCryptoOverviewVisible(): boolean {
  if (typeof window === 'undefined') return true
  try {
    return window.localStorage.getItem(CRYPTO_OVERVIEW_HIDDEN_KEY) !== '1'
  } catch {
    return true
  }
}

export function setCryptoOverviewVisible(visible: boolean): void {
  if (typeof window === 'undefined') return
  try {
    if (visible) {
      window.localStorage.removeItem(CRYPTO_OVERVIEW_HIDDEN_KEY)
    } else {
      window.localStorage.setItem(CRYPTO_OVERVIEW_HIDDEN_KEY, '1')
    }
  } catch {
    // Private browsing or a disabled storage must not break the TMA.
  }
}

export function formatCryptoQuantity(value: string): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 12 }).format(number)
}
