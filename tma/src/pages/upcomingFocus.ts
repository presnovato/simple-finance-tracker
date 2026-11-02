import type { UpcomingFocus } from '../types'

/**
 * Что делать с запросом перехода к ближайшему платежу (spec 04).
 *
 * - `ignore` — запроса нет, он уже обработан или относится к другому виду
 *   сущности (одинаковый id у подписки и кредита безопасен);
 * - `wait` — данные вкладки ещё не загружены, нужно дождаться ответа;
 * - `missing` — record исчезла/недоступна, открывать случайную запись нельзя;
 * - `open` — можно открыть точную запись по `kind` + `id`.
 */
export type UpcomingFocusResolution =
  | { status: 'ignore' }
  | { status: 'wait' }
  | { status: 'missing'; focus: UpcomingFocus }
  | { status: 'open'; focus: UpcomingFocus }

export function resolveUpcomingFocus(
  focus: UpcomingFocus | null | undefined,
  kind: UpcomingFocus['kind'],
  handledNonce: number,
  loaded: boolean,
  availableIds: readonly number[],
): UpcomingFocusResolution {
  if (!focus || focus.kind !== kind || focus.nonce === handledNonce) {
    return { status: 'ignore' }
  }
  if (!loaded) return { status: 'wait' }
  if (!availableIds.includes(focus.id)) return { status: 'missing', focus }
  return { status: 'open', focus }
}
