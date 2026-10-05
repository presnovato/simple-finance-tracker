import { useRef, useState } from 'react'
import {
  TKButton,
  TKInput,
  TKNoticeBar,
  TKSelect,
  TKTextarea,
  TKNativeField,
} from 'tg-mini-app-uikit'

import { api, createOperation, submissionKey } from '../../api'
import type { SubmissionKey } from '../../api'
import {
  buildOperationCreatePayload,
  buildOperationPatch,
  emptyOperationForm,
  formFromOperation,
  validateOperationForm,
} from '../../operationForm'
import { haptic } from '../../telegram'
import type { Categories, Operation, OperationType, TransferDirection } from '../../types'

interface EditorProps {
  operation: Operation | null
  categories: Categories
  onSaved: () => void
  onConfirm?: () => void
  onDelete?: () => void
}

export function OperationEditor({ operation, categories, onSaved, onConfirm, onDelete }: EditorProps) {
  const initialForm = operation ? formFromOperation(operation) : emptyOperationForm()
  const baseline = useRef(initialForm)
  const [form, setForm] = useState(initialForm)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const lastCreate = useRef<SubmissionKey | null>(null)
  const activeOptions = form.type === 'доход' ? categories.income : categories.expense
  const currentCategory = operation?.category ?? ''
  // Архивное значение текущей операции остаётся доступным при редактировании.
  const categoryOptions = currentCategory && !activeOptions.includes(currentCategory)
    ? [...activeOptions, currentCategory]
    : activeOptions

  const submit = async () => {
    setSaving(true); setError('')
    try {
      const validationError = validateOperationForm(form)
      if (validationError) {
        setError(validationError)
        return
      }
      if (operation) {
        const patch = buildOperationPatch(form, baseline.current)
        if (!Object.keys(patch).length) {
          onSaved()
          return
        }
        await api<Operation>(`/api/operations/${operation.id}`, {
          method: 'PATCH', body: JSON.stringify(patch),
        })
        baseline.current = form
        onSaved()
      } else {
        const payload = buildOperationCreatePayload(form)
        lastCreate.current = submissionKey(lastCreate.current, payload)
        await createOperation(payload, lastCreate.current.key)
        onSaved()
      }
      haptic('medium')
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="history-editor-form">
      <TKInput
        label="Сумма"
        inputMode="decimal"
        value={form.amount}
        onChange={(value) => setForm({ ...form, amount: value.replace(',', '.') })}
      />
      <TKSelect
        label="Тип"
        options={[
          { value: 'расход', label: 'Расход' },
          { value: 'доход', label: 'Доход' },
          { value: 'перевод', label: 'Перевод' },
        ]}
        value={form.type}
        onChange={(value) => {
          const nextType = value as OperationType
          const nextOptions = nextType === 'доход' ? categories.income : categories.expense
          setForm((current) => ({
            ...current,
            type: nextType,
            category: nextType === 'перевод'
              ? ''
              : nextOptions.includes(current.category) ? current.category : '',
            transfer_direction: nextType === 'перевод'
              ? current.transfer_direction || 'out'
              : 'out',
          }))
        }}
      />
      <TKSelect
        label="Категория"
        disabled={form.type === 'перевод'}
        placeholder="Без категории"
        options={['', ...categoryOptions].map((item) => ({ value: item, label: item || 'Без категории' }))}
        value={form.category}
        onChange={(value) => setForm((current) => ({ ...current, category: value }))}
      />
      {form.type === 'перевод' && (
        <TKSelect
          label="Направление"
          options={[
            { value: 'in', label: 'Входящий' },
            { value: 'out', label: 'Исходящий' },
            { value: 'self', label: 'Между своими' },
          ]}
          value={form.transfer_direction}
          onChange={(value) => setForm((current) => ({
            ...current,
            transfer_direction: value as TransferDirection,
          }))}
        />
      )}
      <TKNativeField
        type="date"
        label="Дата"
        value={form.op_date}
        onChange={(value) => setForm({ ...form, op_date: value })}
      />
      <TKTextarea
        label="Комментарий"
        rows={2}
        value={form.comment}
        onChange={(value) => setForm({ ...form, comment: value })}
      />
      {operation && (
        <div className="history-editor-note">
          <TKTextarea
            label="Заметка"
            rows={2}
            value={form.note}
            onChange={(value) => setForm({ ...form, note: value })}
          />
          <span>
            Не перезаписывается ботом
          </span>
        </div>
      )}
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      {operation?.needs_review && onConfirm && (
        <TKButton full variant="tonal" onClick={onConfirm}>Подтвердить запись</TKButton>
      )}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>
        {operation ? 'Сохранить' : 'Записать операцию'}
      </TKButton>
      {operation && onDelete && (
        <TKButton full variant="destructive" onClick={onDelete}>Удалить операцию</TKButton>
      )}
    </div>
  )
}
