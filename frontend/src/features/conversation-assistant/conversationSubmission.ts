import type { MessageCreate } from './types'

export function prepareSubmission(
  pending: MessageCreate | null, draft: string, attachments: string[],
): MessageCreate | null {
  const content = draft.trim() ? draft : '请查看我上传的文件。'
  if (pending) {
    const sameAttachments = pending.file_ids.length === attachments.length &&
      pending.file_ids.every((id, index) => id === attachments[index])
    return pending.content === content && sameAttachments ? pending : null
  }
  return { client_message_id: crypto.randomUUID(), content, file_ids: [...attachments] }
}
