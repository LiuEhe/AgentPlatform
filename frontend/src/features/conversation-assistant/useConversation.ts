import { computed, onBeforeUnmount, ref } from 'vue'
import * as api from '../../api/conversations'
import { ApiError } from '../../api/client'
import type { AuthController } from '../auth/types'
import { isTerminal } from './types'
import type { SessionSummary, SessionView, FileView, MessageCreate, MessageView, RunView } from './types'
import { ConversationSnapshots, type RetryAction } from './conversationSnapshots'
import { createConversationDeletions } from './conversationDeletions'
import { mergeMessages, mergeSessions } from './conversationHistory'
import { createConversationStream } from './conversationStream'
import { prepareSubmission } from './conversationSubmission'

const SESSION_KEY = 'agent-platform-session'
const PENDING_KEY = 'agent-platform-session-pending-id'
const DELETIONS_KEY = 'agent-platform-session-deletions'

function isMissing(reason: unknown) {
  return reason instanceof ApiError && reason.status === 404
}

export function useConversation(options?: { auth: AuthController }) {
  const owner = options?.auth.capture()
  const storageKey = (key: string) => owner ? `${key}:${owner.userId}` : key
  let identityCleared = false
  const sessionId = ref<string | null>(null)
  const sessions = ref<SessionSummary[]>([])
  const messages = ref<MessageView[]>([])
  const files = ref<FileView[]>([])
  const selectedFileIds = ref<string[]>([])
  const draft = ref('')
  const activeRun = ref<RunView | null>(null)
  const streamingText = ref('')
  const error = ref('')
  const initializing = ref(false)
  const sending = ref(false)
  const uploading = ref(false)
  const earlierCursor = ref<number | null>(null)
  const receivedSequence = ref(0)
  const hasEarlierMessages = computed(() => earlierCursor.value !== null)
  const loadingEarlier = ref(false)
  const loadingHistory = ref(false)
  const deletions = createConversationDeletions({
    canDelete: () => canDelete.value,
    readPending: () => stored(DELETIONS_KEY),
    writePending: value => remember(DELETIONS_KEY, value),
    remove: (id, signal) => api.deleteSession(id, signal),
    onRemoved: async (id, resume) => {
      const wasCurrent = id === sessionId.value
      invalidateSession(id)
      if (wasCurrent && resume) await initializeSession()
    },
  })
  const { deleting, deletionError, pendingDeletions, deleteSession, retryDeletion } = deletions
  const deletedSessionIds = new Set(pendingDeletions.value.filter(item => item.phase === 'cleanup_pending').map(item => item.session_id))
  let historyVersion = 0
  const listCursor = ref<string | null>(null)
  const hasMoreSessions = computed(() => listCursor.value !== null)
  let pending: MessageCreate | null = null
  const retryAction = ref<RetryAction>(null)
  const retryable = computed(() => retryAction.value !== null)
  let retryTarget: string | null = null
  const snapshots = new ConversationSnapshots()
  let generation = 0
  let controller = new AbortController()
  const stream = createConversationStream()
  const busy = computed(() => initializing.value || sending.value || uploading.value || deleting.value ||
    Boolean(activeRun.value && !isTerminal(activeRun.value.status)))
  const canDelete = computed(() => !initializing.value && !sending.value && !uploading.value && !deleting.value)

  function hasDraft(id: string) { return id === sessionId.value ? Boolean(draft.value) : snapshots.hasDraft(id) }
  function invalidateSession(id: string) {
    deletedSessionIds.add(id)
    historyVersion += 1
    loadingHistory.value = false
    sessions.value = sessions.value.filter(item => item.session_id !== id)
    snapshots.invalidate(id)
    if (retryTarget === id) { retryTarget = null; retryAction.value = null }
    if (stored(SESSION_KEY) === id) { clearStoredSession() }
    if (sessionId.value === id) {
      resetRequests()
      restore(null)
    }
  }
  function saveCurrent() {
    const id = sessionId.value
    if (!id) return
    snapshots.save(id, {
      messages: messages.value, files: files.value,
      selectedIds: selectedFileIds.value, draft: draft.value, run: activeRun.value,
      pending, retryAction: retryAction.value ?? (pending ? 'send' : null), retryTarget, error: error.value,
      streamingText: streamingText.value, earlierCursor: earlierCursor.value, receivedSequence: receivedSequence.value,
    })
  }
  function restore(id: string | null) {
    const snapshot = snapshots.restore(id)
    sessionId.value = id
    messages.value = snapshot.messages
    files.value = snapshot.files
    selectedFileIds.value = snapshot.selectedIds
    draft.value = snapshot.draft
    activeRun.value = snapshot.run
    pending = snapshot.pending
    error.value = snapshot.error
    retryAction.value = snapshot.retryAction
    retryTarget = snapshot.retryTarget
    streamingText.value = snapshot.streamingText
    earlierCursor.value = snapshot.earlierCursor
    receivedSequence.value = snapshot.receivedSequence
  }
  async function resume(view: SessionView, current: number) {
    if (view.active_run_id) watchRun(view.session_id, view.active_run_id, current)
    else {
      activeRun.value = null
      streamingText.value = ''
      if (pending) {
        retryAction.value = 'send'
        error.value = '上一条消息的发送结果尚未确认，请重试以确认，避免重复执行。'
      }
    }
  }

  function remember(key: string, value: string | null) {
    if (identityCleared || (owner && !options?.auth.isCurrent(owner))) return
    key = storageKey(key)
    try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value) } catch { /* storage may be disabled */ }
  }
  function stored(key: string) {
    try { return sessionStorage.getItem(storageKey(key)) } catch { return null }
  }
  function clearStoredSession() {
    remember(SESSION_KEY, null)
    remember(PENDING_KEY, null)
  }
  function receive(view: SessionView, direction: 'latest' | 'earlier' | 'after' = 'latest') {
    if (deletedSessionIds.has(view.session_id)) return
    if (direction === 'earlier' || (direction === 'latest' && !messages.value.length)) earlierCursor.value = view.next_before_sequence ?? null
    if (direction !== 'earlier') receivedSequence.value = Math.max(receivedSequence.value, ...view.messages.map(m => m.sequence))
    sessionId.value = view.session_id
    remember(SESSION_KEY, view.session_id)
    messages.value = mergeMessages(messages.value, view.messages)
    files.value = view.files
    const summary = { session_id: view.session_id, agent_id: view.agent_id, title: view.title,
      created_at: view.created_at, updated_at: view.updated_at }
    sessions.value = mergeSessions(sessions.value, [summary], deletedSessionIds)
    saveCurrent()
  }
  function fail(reason: unknown) {
    if (reason instanceof ApiError && reason.code === 'CONVERSATION_NOT_FOUND' && sessionId.value) {
      invalidateSession(sessionId.value)
      queueMicrotask(() => { void initialize() })
      return
    }
    error.value = reason instanceof Error ? reason.message : '操作未完成，请稍后重试。'
  }
  async function receiveLatest(view: SessionView, current: number) {
    let after = receivedSequence.value
    if (messages.value.length) {
      while (after < view.last_sequence) {
        const page = await api.getSession(view.session_id, { afterSequence: after }, controller.signal)
        if (current !== generation || sessionId.value !== view.session_id) return false
        const last = page.messages.at(-1)?.sequence
        if (last === undefined || last <= after) throw new Error('消息分页位置无效，请重新连接。')
        receive(page, 'after')
        after = last
      }
    }
    if (current !== generation) return false
    receive(view)
    return true
  }
  function resetRequests() {
    generation += 1
    controller.abort()
    controller = new AbortController()
    stream.close()
    sending.value = false
    uploading.value = false
    loadingEarlier.value = false
    loadingHistory.value = false
    retryAction.value = null
    retryTarget = null
    return generation
  }
  function clearPending() {
    pending = null
    remember(PENDING_KEY, null)
  }
  function clearComposer() {
    clearPending()
    draft.value = ''
    selectedFileIds.value = []
  }
  function acceptRun(run: RunView) {
    activeRun.value = run
    if (pending?.client_message_id === run.client_message_id) clearComposer()
    if (run.message) messages.value = mergeMessages(messages.value, [run.message])
  }
  function isCurrentRun(id: string, runId: string, current: number) {
    return current === generation && id === sessionId.value && activeRun.value?.run_id === runId
  }
  async function refreshCompleted(id: string, runId: string, current: number, version: number) {
    const valid = () => version === stream.version && isCurrentRun(id, runId, current)
    try {
      let after = receivedSequence.value
      while (valid()) {
        const view = await api.getSession(id, { afterSequence: after }, controller.signal)
        if (!valid()) return
        receive(view, 'after')
        if (!view.has_more) break
        if (view.next_after_sequence === null || view.next_after_sequence <= after) throw new Error('消息分页位置无效，请重新连接。')
        after = view.next_after_sequence
      }
    } catch (reason) {
      if (!valid() || controller.signal.aborted) return
      fail(reason)
      retryAction.value = isMissing(reason) ? null : 'refresh'
    }
  }
  function finishRun(id: string, run: RunView, current: number) {
    stream.close()
    acceptRun(run)
    streamingText.value = ''
    error.value = run.error?.message ?? ''
    retryAction.value = null
    void refreshCompleted(id, run.run_id, current, stream.version)
  }
  function watchRun(id: string, runId: string, current: number) {
    if (activeRun.value?.run_id !== runId) {
      streamingText.value = ''
      activeRun.value = { run_id: runId, client_message_id: '', status: 'running', stage: '正在连接任务…', message: null, error: null }
    }
    stream.open(id, runId, {
      signal: controller.signal,
      isCurrent: () => isCurrentRun(id, runId, current),
      onEvent(event) {
        if (event.event === 'delta') {
          streamingText.value += event.text
          return
        }
        if (event.event === 'snapshot') streamingText.value = event.text
        if (isTerminal(event.run.status)) finishRun(id, event.run, current)
        else acceptRun(event.run)
      },
      onReconnecting: reconnecting => { error.value = reconnecting ? '连接中断，正在重新连接…' : '' },
      onDisconnected(reason, expired) {
        fail(reason)
        if (expired) { activeRun.value = null; streamingText.value = '' }
        retryAction.value = expired ? null : 'stream'
      },
    })
  }
  async function initialize() {
    deletions.resume()
    if (!deleting.value) await initializeSession()
  }
  async function initializeSession() {
    saveCurrent()
    const current = resetRequests()
    initializing.value = true
    error.value = ''
    try {
      const list = await api.listSessions({}, controller.signal)
      if (current !== generation) return
      sessions.value = list.items.filter(item => !deletedSessionIds.has(item.session_id))
      listCursor.value = list.next_cursor
      const ids = new Set([sessionId.value, stored(SESSION_KEY), ...list.items.map(item => item.session_id)])
      let view: SessionView | undefined
      for (const id of ids) {
        if (!id || deletedSessionIds.has(id)) continue
        try {
          view = await api.getSession(id, {}, controller.signal)
          break
        } catch (reason) {
          if (current !== generation) return
          if (!isMissing(reason)) throw reason
          // 当前初始化已隔离旧请求；只失效目标，保持本轮请求代次。
          deletedSessionIds.add(id)
          snapshots.discard(id)
          sessions.value = sessions.value.filter(item => item.session_id !== id)
          if (sessionId.value === id) restore(null)
          clearStoredSession()
        }
      }
      if (current !== generation) return
      if (!view) {
        restore(null)
        clearStoredSession()
        return
      }
      if (sessionId.value !== view.session_id) restore(view.session_id)
      if (!await receiveLatest(view, current)) return
      if (!pending) remember(PENDING_KEY, null)
      await resume(view, current)
    } catch (reason) {
      if (current === generation && !controller.signal.aborted) {
        fail(reason)
        retryAction.value = isMissing(reason) ? 'create' : 'initialize'
      }
    }
    finally { if (current === generation) initializing.value = false }
  }
  async function loadMoreSessions() {
    if (deleting.value || loadingHistory.value || !listCursor.value) return
    const current = generation
    const version = historyVersion
    loadingHistory.value = true
    try {
      const page = await api.listSessions({ cursor: listCursor.value }, controller.signal)
      if (current !== generation || version !== historyVersion) return
      sessions.value = mergeSessions(sessions.value, page.items, deletedSessionIds)
      listCursor.value = page.next_cursor
    } catch (reason) { if (current === generation && !controller.signal.aborted) fail(reason) }
    finally { if (current === generation && version === historyVersion) loadingHistory.value = false }
  }
  async function loadEarlierMessages() {
    const id = sessionId.value, before = earlierCursor.value, current = generation
    if (deleting.value || !id || before === null || loadingEarlier.value) return
    loadingEarlier.value = true
    try {
      const page = await api.getSession(id, { beforeSequence: before }, controller.signal)
      if (current !== generation || id !== sessionId.value) return
      receive(page, 'earlier')
    } catch (reason) { if (current === generation && !controller.signal.aborted) fail(reason) }
    finally { if (current === generation) loadingEarlier.value = false }
  }
  async function newSession() {
    if (initializing.value || deleting.value) return
    // 当前仍是可用的空白对话时复用它，避免重复点击堆积空会话。
    if (sessionId.value && !busy.value && !messages.value.length && !files.value.length &&
      !draft.value && !pending && !activeRun.value && !error.value) return
    saveCurrent()
    const previousId = sessionId.value
    const current = resetRequests()
    initializing.value = true
    error.value = ''
    try {
      const view = await api.createSession(controller.signal)
      if (current !== generation) return
      restore(null)
      remember(PENDING_KEY, null)
      receive(view)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      restore(previousId)
      fail(reason)
      retryAction.value = 'create'
      // 新会话创建失败时恢复原会话的实际状态，避免旧请求的标记永久禁用输入。
      if (previousId) {
        try {
          const previous = await api.getSession(previousId, {}, controller.signal)
          if (current !== generation) return
          if (!await receiveLatest(previous, current)) return
          await resume(previous, current)
        } catch { /* 保留创建失败提示，仍可再次新建 */ }
      }
    }
    finally { if (current === generation) initializing.value = false }
  }
  async function switchSession(id: string) {
    if (deleting.value || deletedSessionIds.has(id)) return
    if (id === sessionId.value) return
    saveCurrent()
    const previousId = sessionId.value
    const current = resetRequests()
    initializing.value = true
    try {
      const view = await api.getSession(id, {}, controller.signal)
      if (current !== generation) return
      restore(id)
      if (!await receiveLatest(view, current)) return
      remember(PENDING_KEY, pending?.client_message_id ?? null)
      await resume(view, current)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      restore(previousId)
      const missing = isMissing(reason)
      if (missing) invalidateSession(id)
      error.value = missing
        ? '这段会话不存在。当前对话与输入仍保留。'
        : reason instanceof Error ? reason.message : '切换对话失败，请重试。'
      retryAction.value = missing ? null : 'switch'
      retryTarget = id
      if (previousId && activeRun.value && !isTerminal(activeRun.value.status)) {
        watchRun(previousId, activeRun.value.run_id, current)
      }
    } finally { if (current === generation) initializing.value = false }
  }
  async function send() {
    const id = sessionId.value
    if (!id || busy.value || (!draft.value.trim() && !selectedFileIds.value.length)) return
    const current = generation
    const submission = prepareSubmission(pending, draft.value, selectedFileIds.value)
    if (!submission) {
      error.value = '上一条消息的发送状态尚未确认，请先重试，或新建对话。'
      return
    }
    pending = submission
    const submittedId = submission.client_message_id
    remember(PENDING_KEY, pending.client_message_id)
    sending.value = true
    error.value = ''
    try {
      const run = await api.sendSessionMessage(id, pending, controller.signal)
      if (current !== generation) return
      clearComposer()
      retryAction.value = null
      activeRun.value = run
      const view = await api.getSession(id, {}, controller.signal)
      if (current !== generation) return
      if (!await receiveLatest(view, current)) return
      watchRun(id, run.run_id, current)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      fail(reason)
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 408) {
        clearPending()
      }
      retryAction.value = activeRun.value?.client_message_id === submittedId ? 'stream' : 'send'
    } finally { if (current === generation) sending.value = false }
  }
  async function upload(file: File) {
    const id = sessionId.value
    if (!id || busy.value) return
    const current = generation
    uploading.value = true; error.value = ''
    try {
      const result = await api.uploadSessionFile(id, file, controller.signal)
      if (current !== generation) return
      files.value.push(result)
      selectedFileIds.value.push(result.file_id)
    } catch (reason) { if (current === generation && !controller.signal.aborted) fail(reason) }
    finally { if (current === generation) uploading.value = false }
  }
  async function stop() {
    const id = sessionId.value, run = activeRun.value, current = generation
    if (deleting.value || !id || !run || initializing.value || isTerminal(run.status)) return
    try {
      const result = await api.cancelSessionRun(id, run.run_id)
      if (!isCurrentRun(id, run.run_id, current)) return
      if (isTerminal(result.status)) finishRun(id, result, current)
      else {
        acceptRun(result)
        if (!stream.connected) watchRun(id, run.run_id, current)
      }
    } catch (reason) { if (current === generation) fail(reason) }
  }
  async function retry() {
    if (deleting.value) return
    const action = retryAction.value
    if (action === 'create') { await newSession(); return }
    error.value = ''; retryAction.value = null
    if (action === 'initialize') await initialize()
    else if (action === 'switch' && retryTarget) await switchSession(retryTarget)
    else if (action === 'stream' && activeRun.value && sessionId.value) watchRun(sessionId.value, activeRun.value.run_id, generation)
    else if (action === 'refresh' && activeRun.value && sessionId.value) await refreshCompleted(sessionId.value, activeRun.value.run_id, generation, stream.version)
    else if (action === 'send' || pending) await send()
    else if (activeRun.value && sessionId.value) watchRun(sessionId.value, activeRun.value.run_id, generation)
  }
  function suspend() {
    deletions.suspend()
    saveCurrent()
    resetRequests()
    initializing.value = false
  }
  function resetForIdentityChange() {
    identityCleared = true
    suspend()
    snapshots.clear(); deletedSessionIds.clear(); deletions.clear()
    sessionId.value = null; sessions.value = []; messages.value = []; files.value = []
    selectedFileIds.value = []; draft.value = ''; activeRun.value = null; streamingText.value = ''
    pending = null
    pendingDeletions.value = []; error.value = ''; deletionError.value = ''
    listCursor.value = null; earlierCursor.value = null
  }
  const unregister = options?.auth.registerCleanup(resetForIdentityChange)
  onBeforeUnmount(() => { unregister?.(); resetForIdentityChange() })
  return { resetForIdentityChange, sessionId, sessions, messages, files, selectedFileIds, draft, activeRun, streamingText, busy,
    deleting, canDelete, pendingDeletions, deletionError, deleteSession, retryDeletion, hasDraft,
    initializing, uploading, error, retryable, initialize, send, upload, stop, newSession, switchSession, suspend, retry,
    loadMoreSessions, loadEarlierMessages, hasMoreSessions, hasEarlierMessages, loadingHistory, loadingEarlier }
}
