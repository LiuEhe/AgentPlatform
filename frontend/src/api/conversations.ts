import { ApiError, createApiError, getApiBaseUrl } from './client'
import { isTerminal } from '../features/conversation-assistant/types'
import type { ConversationView, DocumentView, MessageCreate, RunEvent, RunView } from '../features/conversation-assistant/types'

const root = '/api/v1/conversations'
const path = (id: string) => `${root}/${encodeURIComponent(id)}`

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${getApiBaseUrl()}${url}`, init)
    if (!response.ok) throw await createApiError(response, '会话操作失败，请稍后重试。')
    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError || init.signal?.aborted) throw error
    throw new ApiError({ status: 0, message: '会话连接中断，请检查网络后重试。' })
  }
}

export const createConversation = (signal?: AbortSignal) =>
  request<ConversationView>(root, { method: 'POST', signal })
export const getConversation = (id: string, afterSequence = 0, signal?: AbortSignal) =>
  request<ConversationView>(`${path(id)}?after_sequence=${afterSequence}`, { signal })
export const uploadConversationDocument = (id: string, file: File, signal?: AbortSignal) => {
  const body = new FormData()
  body.append('file', file)
  return request<DocumentView>(`${path(id)}/documents`, { method: 'POST', body, signal })
}
export const sendConversationMessage = (id: string, input: MessageCreate, signal?: AbortSignal) =>
  request<RunView>(`${path(id)}/messages`, {
    method: 'POST', body: JSON.stringify(input), headers: { 'Content-Type': 'application/json' }, signal,
  })
export const getConversationRun = (id: string, runId: string, signal?: AbortSignal) =>
  request<RunView>(`${path(id)}/runs/${encodeURIComponent(runId)}`, { signal })
export const cancelConversationRun = (id: string, runId: string) =>
  request<RunView>(`${path(id)}/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })

export interface RunSubscriptionHandlers {
  onEvent: (event: RunEvent) => void
  onError: (reason: unknown) => void
  onReconnecting?: () => void
}

export function subscribeConversationRun(id: string, runId: string, handlers: RunSubscriptionHandlers, signal?: AbortSignal): () => void {
  if (signal?.aborted) return () => {}
  const source = new EventSource(`${getApiBaseUrl()}${path(id)}/runs/${encodeURIComponent(runId)}/events`)
  let closed = false
  let failures = 0
  function close() {
    if (closed) return
    closed = true
    source.close()
    signal?.removeEventListener('abort', close)
  }
  function fail() {
    close()
    handlers.onError(new ApiError({ status: 0, message: '流式连接中断，任务可能仍在执行，请重试连接。' }))
  }
  for (const kind of ['snapshot', 'delta', 'state', 'done'] as const) {
    source.addEventListener(kind, (message: MessageEvent<string>) => {
      if (closed) return
      let event: RunEvent
      try {
        event = JSON.parse(message.data) as RunEvent
        if (event.event !== kind ||
          ((kind === 'delta' || kind === 'snapshot') && typeof ('text' in event && event.text) !== 'string') ||
          (event.event !== 'delta' && (!event.run || event.run.id !== runId))) throw new Error('Invalid stream event')
      } catch { fail(); return }
      failures = 0
      if (event.event === 'done' || (event.event !== 'delta' && isTerminal(event.run.status))) close()
      handlers.onEvent(event)
    })
  }
  source.onerror = () => {
    if (closed) return
    if (++failures >= 3 || source.readyState === EventSource.CLOSED) fail()
    else handlers.onReconnecting?.()
  }
  signal?.addEventListener('abort', close, { once: true })
  return close
}
