import { ApiError, createApiError, getApiBaseUrl } from './client'
import type { ConversationView, DocumentView, MessageCreate, RunView } from '../features/conversation-assistant/types'

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
