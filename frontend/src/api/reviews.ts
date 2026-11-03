import { ApiError, apiRequest } from './client'
import type { ReviewSubmission } from '../features/institution-review/types'

export async function submitReview(submission: ReviewSubmission, signal?: AbortSignal): Promise<string> {
  const body = new FormData()
  body.append('file', submission.file)
  body.append('review_mode', submission.mode)
  if (submission.mode === 'standard_document') {
    body.append('standard_file', submission.standardFile)
  }

  return apiRequest<string>('/api/v1/reviews', {
    method: 'POST', body, headers: { Accept: 'text/markdown' }, signal,
  }, 'text')
}

const DOCX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export async function exportReviewToWord(markdown: string, signal?: AbortSignal): Promise<Blob> {
  const blob = await apiRequest<Blob>('/api/v1/documents/export/docx', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: DOCX_MEDIA_TYPE },
    body: JSON.stringify({ markdown }), signal,
  }, 'blob')
  if (blob.type.split(';')[0]?.trim() !== DOCX_MEDIA_TYPE) {
    throw new ApiError({ status: 200, message: '导出服务未返回 Word 文件，请稍后重试。' })
  }
  return blob
}
