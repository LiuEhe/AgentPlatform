import { ApiError, createApiError, getApiBaseUrl } from './client'
import type { ReviewSubmission } from '../features/institution-review/types'

export async function submitReview(submission: ReviewSubmission): Promise<string> {
  const body = new FormData()
  body.append('file', submission.file)
  body.append('review_mode', submission.mode)
  if (submission.mode === 'standard_document') {
    body.append('standard_file', submission.standardFile)
  }

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

const DOCX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export async function exportReviewToWord(markdown: string, signal?: AbortSignal): Promise<Blob> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/v1/documents/export/docx`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: DOCX_MEDIA_TYPE },
      body: JSON.stringify({ markdown }),
      signal,
    })
    if (!response.ok) {
      throw await createApiError(response, 'Word 导出失败，请稍后重试。')
    }
    if (response.headers.get('Content-Type')?.split(';')[0]?.trim() !== DOCX_MEDIA_TYPE) {
      throw new ApiError({ status: response.status, message: '导出服务未返回 Word 文件，请稍后重试。' })
    }
    return await response.blob()
  } catch (error) {
    if (error instanceof ApiError || signal?.aborted) throw error
    throw new ApiError({ status: 0, message: 'Word 文件下载中断，请确认网络连接后重试。' })
  }
}
