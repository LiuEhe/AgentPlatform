import { ref } from 'vue'
import { ApiError } from '../../api/client'
import type { PendingSessionDeletion } from './types'

interface DeletionOptions {
  canDelete(): boolean
  readPending(): string | null
  writePending(value: string | null): void
  remove(id: string, signal: AbortSignal): Promise<void>
  onRemoved(id: string, resume: boolean): Promise<void>
}

function readPending(value: string | null): PendingSessionDeletion[] {
  try {
    const parsed: unknown = JSON.parse(value ?? '[]')
    if (!Array.isArray(parsed)) return []
    const valid = parsed.filter((item): item is PendingSessionDeletion => item &&
      typeof item.session_id === 'string' && item.session_id.length > 0 &&
      (item.phase === 'unconfirmed' || item.phase === 'cleanup_pending'))
    return [...new Map(valid.map(item => [item.session_id, { session_id: item.session_id, phase: item.phase }])).values()]
  } catch { return [] }
}

export function createConversationDeletions(options: DeletionOptions) {
  const deleting = ref(false)
  const deletionError = ref('')
  const pendingDeletions = ref<PendingSessionDeletion[]>(readPending(options.readPending()))
  const requests = new Map<string, number>()
  let version = 0
  let suspended = false
  let controller = new AbortController()

  function setPending(id: string, phase: PendingSessionDeletion['phase'] | null) {
    pendingDeletions.value = pendingDeletions.value.filter(item => item.session_id !== id)
    if (phase) pendingDeletions.value.push({ session_id: id, phase })
    options.writePending(pendingDeletions.value.length ? JSON.stringify(pendingDeletions.value) : null)
  }

  async function deleteSession(id: string) {
    if (!options.canDelete()) return
    const current = ++version
    requests.set(id, current)
    controller = new AbortController()
    const signal = controller.signal
    deleting.value = true
    deletionError.value = ''
    setPending(id, pendingDeletions.value.find(item => item.session_id === id)?.phase ?? 'unconfirmed')
    let removed = false
    try {
      await options.remove(id, signal)
      if (requests.get(id) !== current) return
      setPending(id, null)
      removed = true
    } catch (reason) {
      if (requests.get(id) !== current) return
      if (reason instanceof ApiError && reason.code === 'CONVERSATION_DELETE_INCOMPLETE') {
        setPending(id, 'cleanup_pending')
        if (current === version) deletionError.value = '对话已删除，附件清理未完成。'
        removed = true
      } else if (reason instanceof ApiError && reason.status === 409) {
        setPending(id, null)
        if (current === version) deletionError.value = '请等待上传完成，或停止任务并等其结束后再删除。'
      } else if (current === version && !signal.aborted) deletionError.value = '删除结果尚未确认，请重试。'
    } finally {
      // Confirmed resource results still invalidate cached sessions after page suspension.
      if (removed) await options.onRemoved(id, !suspended && (current === version || !deleting.value))
      if (current === version) deleting.value = false
      if (requests.get(id) === current) requests.delete(id)
    }
  }

  async function retryDeletion(id: string) {
    if (pendingDeletions.value.some(item => item.session_id === id)) await deleteSession(id)
  }

  function suspend() {
    suspended = true
    version += 1
    controller.abort()
    deleting.value = false
  }

  function clear() {
    suspend()
    requests.clear()
    pendingDeletions.value = []
    deletionError.value = ''
  }

  return { deleting, deletionError, pendingDeletions, deleteSession, retryDeletion,
    suspend, resume: () => { suspended = false }, clear }
}
