import { TKButton, TKNoticeBar, TKSheet } from 'tg-mini-app-uikit'

interface Props {
  open: boolean
  title: string
  text: string
  confirmLabel: string
  loading?: boolean
  error?: string
  onClose: () => void
  onConfirm: () => void
}

export function ConfirmSheet({
  open,
  title,
  text,
  confirmLabel,
  loading = false,
  error = '',
  onClose,
  onConfirm,
}: Props) {
  return (
    <TKSheet open={open} onClose={onClose} title={title}>
      <div className="confirm-sheet">
        <p>{text}</p>
        {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
        <div className="confirm-sheet-actions">
          <TKButton full variant="destructive" loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </TKButton>
          <TKButton full variant="plain" disabled={loading} onClick={onClose}>
            Отмена
          </TKButton>
        </div>
      </div>
    </TKSheet>
  )
}
