export interface ApiErrorDetails {
  field?: string
  message?: string
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

export async function createApiError(response: Response): Promise<ApiError> {
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
    : getStatusMessage(response.status)
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
