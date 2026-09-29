import { ApiError, createApiError, getApiBaseUrl } from './client'

export async function submitReview(file: File): Promise<string> {
  const body = new FormData()
  body.append('file', file)

  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}/api/v1/reviews`, {
      method: 'POST',
      body,
      headers: { Accept: 'text/markdown' },
    })
  } catch {
    throw new ApiError({
      status: 0,
      message: '无法连接审核服务，请确认服务已启动后重试。',
    })
  }

  if (!response.ok) throw await createApiError(response)
  return response.text()
}
