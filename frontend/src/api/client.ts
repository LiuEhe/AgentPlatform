import type { AuthTicket } from '../features/auth/types'

export interface ApiErrorDetails {
  field?: string
  message?: string
}

export interface AuthHttpHooks {
  capture(): AuthTicket | null
  isCurrent(ticket: AuthTicket): boolean
  onAuthError(error: ApiError, ticket: AuthTicket): void
}
let authHooks: AuthHttpHooks | undefined
export function installAuthHooks(hooks: AuthHttpHooks) { authHooks = hooks }
export function authStreamContext() {
  const ticket = authHooks?.capture()
  if (!ticket) throw new ApiError({ status: 401, code: 'AUTH_REQUIRED', message: '请先登录。' })
  return { ticket, isCurrent: () => authHooks?.isCurrent(ticket) === true }
}
export async function apiRequest<T>(path: string, init: RequestInit = {}, mode: 'json' | 'text' | 'blob' | 'empty' = 'json',
  policy: 'bound' | 'public-auth' | 'bootstrap' = 'bound', explicitTicket?: AuthTicket): Promise<T> {
  const ticket = policy === 'bound' ? explicitTicket ?? authHooks?.capture() : null
  if (policy === 'bound' && !ticket) throw new ApiError({ status: 401, code: 'AUTH_REQUIRED', message: '请先登录。' })
  const headers = new Headers(init.headers)
  if (ticket) {
    headers.set('X-Auth-Session-ID', ticket.authSessionId)
    if (!['GET', 'HEAD'].includes((init.method ?? 'GET').toUpperCase())) headers.set('X-CSRF-Token', ticket.csrfToken)
  }
  function assertCurrent() {
    if (ticket && !explicitTicket && !authHooks?.isCurrent(ticket)) throw new DOMException('账号状态已变化', 'AbortError')
  }
  assertCurrent()
  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...init, headers, credentials: 'include', cache: 'no-store' })
  assertCurrent()
  if (!response.ok) {
    const error = await createApiError(response)
    assertCurrent()
    if (ticket && authHooks?.isCurrent(ticket)) authHooks.onAuthError(error, ticket)
    throw error
  }
  let result: unknown
  if (response.status === 204 || mode === 'empty') result = undefined
  else if (mode === 'blob') result = await response.blob()
  else if (mode === 'text') result = await response.text()
  else result = await response.json()
  assertCurrent()
  return result as T
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly requestId?: string
  readonly details?: ApiErrorDetails[]

  constructor(input: {
    status: number
    message: string
    code?: string
    requestId?: string
    details?: ApiErrorDetails[]
  }) {
    super(input.message)
    this.name = 'ApiError'
    this.status = input.status
    this.code = input.code
    this.requestId = input.requestId
    this.details = input.details
  }
}

export function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
}

export function getStatusMessage(status: number): string {
  if (status === 413) return '文件超过服务端允许的大小，请压缩后重试。'
  if (status === 415) return '文件格式不受支持，请上传 DOCX 文档。'
  if (status === 503) return '审核服务暂未就绪，请稍后再试。'
  if (status >= 500) return '审核服务暂时出现问题，请稍后重试。'
  return '提交失败，请检查文件后重试。'
}

interface ServerError {
  error?: {
    code?: unknown
    message?: unknown
    request_id?: unknown
    details?: unknown
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export async function createApiError(
  response: Response,
  fallbackMessage?: string,
): Promise<ApiError> {
  let body: ServerError | undefined
  try {
    const parsed: unknown = await response.json()
    if (isRecord(parsed) && isRecord(parsed.error)) {
      body = parsed as ServerError
    }
  } catch {
    // Use status-based copy for non-JSON and empty error responses.
  }

  const error = body?.error
  const message = typeof error?.message === 'string' && error.message.trim()
    ? error.message
    : fallbackMessage ?? getStatusMessage(response.status)
  const code = typeof error?.code === 'string' ? error.code : undefined
  const requestId = typeof error?.request_id === 'string' ? error.request_id : undefined
  const details = Array.isArray(error?.details)
    ? error.details.filter((item): item is ApiErrorDetails => isRecord(item))
    : undefined

  return new ApiError({
    status: response.status,
    message,
    code,
    requestId,
    details,
  })
}
