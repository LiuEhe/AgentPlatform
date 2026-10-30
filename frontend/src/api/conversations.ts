import { ApiError, createApiError, getApiBaseUrl } from './client'
import { isTerminal } from '../features/conversation-assistant/types'
import type { SessionListView, SessionView, FileView, MessageCreate, RunEvent, RunView } from '../features/conversation-assistant/types'

const root = '/api/v1/sessions'
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

export const createSession = (signal?: AbortSignal) =>
  request<SessionView>(root, { method: 'POST', signal })
export interface MessagePageOptions { limit?: number; beforeSequence?: number; afterSequence?: number }
export const getSession = (id: string, options: MessagePageOptions = {}, signal?: AbortSignal) => {
  const query = new URLSearchParams()
  if (options.limit !== undefined) query.set('limit', String(options.limit))
  if (options.beforeSequence !== undefined) query.set('before_sequence', String(options.beforeSequence))
  if (options.afterSequence !== undefined) query.set('after_sequence', String(options.afterSequence))
  return request<SessionView>(`${path(id)}?${query}`, { signal })
}
export const listSessions = (options: { limit?: number; cursor?: string; agentId?: string } = {}, signal?: AbortSignal) => {
  const query = new URLSearchParams({ agent_id: options.agentId ?? 'conversation_assistant' })
  if (options.limit !== undefined) query.set('limit', String(options.limit))
  if (options.cursor) query.set('cursor', options.cursor)
  return request<SessionListView>(`${root}?${query}`, { signal })
}
export const uploadSessionFile = (id: string, file: File, signal?: AbortSignal) => {
  const body = new FormData()
  body.append('file', file)
  return request<FileView>(`${path(id)}/files`, { method: 'POST', body, signal })
}
export const sendSessionMessage = (id: string, input: MessageCreate, signal?: AbortSignal) =>
  request<RunView>(`${path(id)}/messages`, {
    method: 'POST', body: JSON.stringify(input), headers: { 'Content-Type': 'application/json' }, signal,
  })
export const getSessionRun = (id: string, runId: string, signal?: AbortSignal) =>
  request<RunView>(`${path(id)}/runs/${encodeURIComponent(runId)}`, { signal })
export const cancelSessionRun = (id: string, runId: string) =>
  request<RunView>(`${path(id)}/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })

export interface RunSubscriptionHandlers {
  onEvent: (event: RunEvent) => void
  onError: (reason: unknown) => void
  onReconnecting?: () => void
}

export function subscribeSessionRun(id: string, runId: string, handlers: RunSubscriptionHandlers, signal?: AbortSignal): () => void {
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
          (event.event !== 'delta' && (!event.run || event.run.run_id !== runId))) throw new Error('Invalid stream event')
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
