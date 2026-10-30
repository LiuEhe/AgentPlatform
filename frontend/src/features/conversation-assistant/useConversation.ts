import { computed, onBeforeUnmount, ref } from 'vue'
import * as api from '../../api/conversations'
import { ApiError } from '../../api/client'
import { isTerminal } from './types'
import type { SessionSummary, SessionView, FileView, MessageCreate, MessageView, RunView, PendingSessionDeletion } from './types'

const SESSION_KEY = 'agent-platform-session'
const PENDING_KEY = 'agent-platform-session-pending-id'
const DELETIONS_KEY = 'agent-platform-session-deletions'
type RetryAction = 'initialize' | 'create' | 'send' | 'stream' | 'refresh' | 'switch' | null
interface ConversationSnapshot {
  messages: MessageView[]
  files: FileView[]
  selectedIds: string[]
  draft: string
  run: RunView | null
  pending: MessageCreate | null
  retryAction: RetryAction
  retryTarget: string | null
  error: string
  streamingText: string
  earlierCursor: number | null
  receivedSequence: number
}

export function useConversation() {
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
  const retryable = ref(false)
  const earlierCursor = ref<number | null>(null)
  const receivedSequence = ref(0)
  const hasEarlierMessages = computed(() => earlierCursor.value !== null)
  const loadingEarlier = ref(false)
  const loadingHistory = ref(false)
  const deleting = ref(false)
  const deletionError = ref('')
  const pendingDeletions = ref<PendingSessionDeletion[]>(readPendingDeletions())
  const deletedSessionIds = new Set(pendingDeletions.value.filter(item => item.phase === 'cleanup_pending').map(item => item.session_id))
  let historyVersion = 0
  let deletionVersion = 0
  let suspended = false
  const deletionRequests = new Map<string, number>()
  let deletionController = new AbortController()
  const listCursor = ref<string | null>(null)
  const hasMoreSessions = computed(() => listCursor.value !== null)
  let pending: MessageCreate | null = null
  let retryAction: RetryAction = null
  let retryTarget: string | null = null
  const snapshots = new Map<string, ConversationSnapshot>()
  let generation = 0
  let controller = new AbortController()
  let unsubscribe: (() => void) | undefined
  let subscriptionVersion = 0
  const busy = computed(() => initializing.value || sending.value || uploading.value || deleting.value ||
    Boolean(activeRun.value && !isTerminal(activeRun.value.status)))
  const canDelete = computed(() => !initializing.value && !sending.value && !uploading.value && !deleting.value)

  function readPendingDeletions(): PendingSessionDeletion[] {
    try {
      const value: unknown = JSON.parse(stored(DELETIONS_KEY) ?? '[]')
      if (!Array.isArray(value)) return []
      const valid = value.filter((item): item is PendingSessionDeletion => item &&
        typeof item.session_id === 'string' && item.session_id.length > 0 &&
        (item.phase === 'unconfirmed' || item.phase === 'cleanup_pending'))
      return [...new Map(valid.map(item => [item.session_id, { session_id: item.session_id, phase: item.phase }])).values()]
    } catch { return [] }
  }
  function setDeletion(id: string, phase: PendingSessionDeletion['phase'] | null) {
    pendingDeletions.value = pendingDeletions.value.filter(item => item.session_id !== id)
    if (phase) pendingDeletions.value.push({ session_id: id, phase })
    remember(DELETIONS_KEY, pendingDeletions.value.length ? JSON.stringify(pendingDeletions.value) : null)
  }
  function hasDraft(id: string) { return Boolean(id === sessionId.value ? draft.value : snapshots.get(id)?.draft) }
  function invalidateSession(id: string) {
    deletedSessionIds.add(id)
    historyVersion += 1
    loadingHistory.value = false
    sessions.value = sessions.value.filter(item => item.session_id !== id)
    snapshots.delete(id)
    for (const snapshot of snapshots.values()) {
      if (snapshot.retryTarget === id) { snapshot.retryTarget = null; snapshot.retryAction = null }
    }
    if (retryTarget === id) { retryTarget = null; retryAction = null; retryable.value = false }
    if (stored(SESSION_KEY) === id) { remember(SESSION_KEY, null); remember(PENDING_KEY, null) }
    if (sessionId.value === id) {
      resetRequests()
      restore(null)
    }
  }
  async function deleteSession(id: string) {
    if (!canDelete.value) return
    const version = ++deletionVersion
    deletionRequests.set(id, version)
    deletionController = new AbortController()
    const signal = deletionController.signal
    deleting.value = true
    deletionError.value = ''
    const previous = pendingDeletions.value.find(item => item.session_id === id)?.phase
    setDeletion(id, previous ?? 'unconfirmed')
    let removed = false
    try {
      await api.deleteSession(id, signal)
      if (deletionRequests.get(id) !== version) return
      setDeletion(id, null)
      removed = true
    } catch (reason) {
      if (deletionRequests.get(id) !== version) return
      if (reason instanceof ApiError && reason.code === 'CONVERSATION_DELETE_INCOMPLETE') {
        setDeletion(id, 'cleanup_pending')
        if (version === deletionVersion) deletionError.value = '对话已删除，附件清理未完成。'
        removed = true
      } else if (reason instanceof ApiError && reason.status === 409) {
        setDeletion(id, null)
        if (version === deletionVersion) deletionError.value = '请等待上传完成，或停止任务并等其结束后再删除。'
      } else if (version === deletionVersion && !signal.aborted) deletionError.value = '删除结果尚未确认，请重试。'
    } finally {
      // 确定的资源结果独立于页面导航；停用后也必须失效该目标缓存。
      if (removed) {
        const wasCurrent = id === sessionId.value
        invalidateSession(id)
        if (wasCurrent && !suspended && (version === deletionVersion || !deleting.value)) await initializeSession()
      }
      if (version === deletionVersion) deleting.value = false
      if (deletionRequests.get(id) === version) deletionRequests.delete(id)
    }
  }
  async function retryDeletion(id: string) {
    if (pendingDeletions.value.some(item => item.session_id === id)) await deleteSession(id)
  }

  function saveCurrent() {
    const id = sessionId.value
    if (!id) return
    snapshots.set(id, {
      messages: [...messages.value], files: [...files.value],
      selectedIds: [...selectedFileIds.value], draft: draft.value, run: activeRun.value,
      pending, retryAction: retryAction ?? (pending ? 'send' : null), retryTarget, error: error.value,
      streamingText: streamingText.value, earlierCursor: earlierCursor.value, receivedSequence: receivedSequence.value,
    })
  }
  function restore(id: string | null) {
    const snapshot = id ? snapshots.get(id) : undefined
    sessionId.value = id
    messages.value = [...(snapshot?.messages ?? [])]
    files.value = [...(snapshot?.files ?? [])]
    selectedFileIds.value = [...(snapshot?.selectedIds ?? [])]
    draft.value = snapshot?.draft ?? ''
    activeRun.value = snapshot?.run ?? null
    pending = snapshot?.pending ?? null
    error.value = snapshot?.error ?? ''
    retryAction = snapshot?.retryAction ?? null
    retryTarget = snapshot?.retryTarget ?? null
    retryable.value = retryAction !== null
    streamingText.value = snapshot?.streamingText ?? ''
    earlierCursor.value = snapshot?.earlierCursor ?? null
    receivedSequence.value = snapshot?.receivedSequence ?? 0
  }
  async function resume(view: SessionView, current: number) {
    if (view.active_run_id) watchRun(view.session_id, view.active_run_id, current)
    else {
      activeRun.value = null
      streamingText.value = ''
      if (pending) {
        retryable.value = true
        retryAction = 'send'
        error.value = '上一条消息的发送结果尚未确认，请重试以确认，避免重复执行。'
      }
    }
  }

  function remember(key: string, value: string | null) {
    try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value) } catch { /* storage may be disabled */ }
  }
  function stored(key: string) {
    try { return sessionStorage.getItem(key) } catch { return null }
  }
  function merge(incoming: MessageView[]) {
    const indexed = new Map(messages.value.map(message => [message.message_id, message]))
    incoming.forEach(message => indexed.set(message.message_id, message))
    messages.value = [...indexed.values()].sort((a, b) => a.sequence - b.sequence)
  }
  function receive(view: SessionView, direction: 'latest' | 'earlier' | 'after' = 'latest') {
    if (deletedSessionIds.has(view.session_id)) return
    if (direction === 'earlier' || (direction === 'latest' && !messages.value.length)) earlierCursor.value = view.next_before_sequence ?? null
    if (direction !== 'earlier') receivedSequence.value = Math.max(receivedSequence.value, ...view.messages.map(m => m.sequence))
    sessionId.value = view.session_id
    remember(SESSION_KEY, view.session_id)
    merge(view.messages)
    files.value = view.files
    const summary = { session_id: view.session_id, agent_id: view.agent_id, title: view.title,
      created_at: view.created_at, updated_at: view.updated_at }
    const existing = sessions.value.find(item => item.session_id === view.session_id)
    if (existing) Object.assign(existing, summary)
    else sessions.value.unshift(summary)
    sessions.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.session_id.localeCompare(a.session_id))
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
    closeStream()
    sending.value = false
    uploading.value = false
    loadingEarlier.value = false
    loadingHistory.value = false
    retryable.value = false
    retryAction = null
    retryTarget = null
    return generation
  }
  function closeStream() {
    subscriptionVersion += 1
    unsubscribe?.()
    unsubscribe = undefined
  }
  function acceptRun(run: RunView) {
    activeRun.value = run
    if (pending?.client_message_id === run.client_message_id) {
      pending = null
      draft.value = ''
      selectedFileIds.value = []
      remember(PENDING_KEY, null)
    }
    if (run.message) merge([run.message])
  }
  async function refreshCompleted(id: string, runId: string, current: number, version: number) {
    const valid = () => current === generation && version === subscriptionVersion &&
      id === sessionId.value && activeRun.value?.run_id === runId
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
      retryable.value = !(reason instanceof ApiError && reason.status === 404)
      retryAction = retryable.value ? 'refresh' : null
    }
  }
  function finishRun(id: string, run: RunView, current: number) {
    closeStream()
    acceptRun(run)
    streamingText.value = ''
    error.value = run.error?.message ?? ''
    retryable.value = false; retryAction = null
    void refreshCompleted(id, run.run_id, current, subscriptionVersion)
  }
  function watchRun(id: string, runId: string, current: number) {
    closeStream()
    const version = subscriptionVersion
    let reconnecting = false
    if (activeRun.value?.run_id !== runId) {
      streamingText.value = ''
      activeRun.value = { run_id: runId, client_message_id: '', status: 'running', stage: '正在连接任务…', message: null, error: null }
    }
    const valid = () => current === generation && version === subscriptionVersion &&
      id === sessionId.value && activeRun.value?.run_id === runId
    async function disconnected(reason: unknown) {
      if (!valid()) return
      closeStream()
      const recoveryVersion = subscriptionVersion
      const recoveryValid = () => current === generation && recoveryVersion === subscriptionVersion && id === sessionId.value && activeRun.value?.run_id === runId
      try {
        // 只查询一次以识别终态/失效；手动重试重新订阅，不回退到定时查询。
        const run = await api.getSessionRun(id, runId, controller.signal)
        if (!recoveryValid()) return
        if (isTerminal(run.status)) { finishRun(id, run, current); return }
        acceptRun(run)
        fail(reason); retryable.value = true; retryAction = 'stream'
      } catch (failure) {
        if (!recoveryValid() || controller.signal.aborted) return
        fail(failure)
        const expired = failure instanceof ApiError && failure.status === 404
        if (expired) { activeRun.value = null; streamingText.value = '' }
        retryable.value = !expired; retryAction = expired ? null : 'stream'
      }
    }
    try {
      unsubscribe = api.subscribeSessionRun(id, runId, {
        onEvent(event) {
          if (!valid()) return
          if (reconnecting) { error.value = ''; reconnecting = false }
          if (event.event === 'delta') { streamingText.value += event.text; return }
          acceptRun(event.run)
          if (event.event === 'snapshot') streamingText.value = event.text
          if (isTerminal(event.run.status)) finishRun(id, event.run, current)
        },
        onReconnecting() {
          if (!valid()) return
          reconnecting = true; error.value = '连接中断，正在重新连接…'
        },
        onError: reason => { void disconnected(reason) },
      }, controller.signal)
    } catch (reason) { void disconnected(reason) }
  }
  async function initialize() {
    suspended = false
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
          if (!(reason instanceof ApiError && reason.status === 404)) throw reason
          // 当前初始化已隔离旧请求；只失效目标，保持本轮请求代次。
          deletedSessionIds.add(id)
          snapshots.delete(id)
          sessions.value = sessions.value.filter(item => item.session_id !== id)
          if (sessionId.value === id) restore(null)
          remember(SESSION_KEY, null); remember(PENDING_KEY, null)
        }
      }
      if (current !== generation) return
      if (!view) {
        restore(null)
        remember(SESSION_KEY, null); remember(PENDING_KEY, null)
        return
      }
      if (sessionId.value !== view.session_id) restore(view.session_id)
      if (!await receiveLatest(view, current)) return
      if (!pending) remember(PENDING_KEY, null)
      await resume(view, current)
    } catch (reason) {
      if (current === generation && !controller.signal.aborted) {
        fail(reason)
        retryable.value = true
        retryAction = reason instanceof ApiError && reason.status === 404 ? 'create' : 'initialize'
      }
    }
    finally { if (current === generation) initializing.value = false }
  }
  function mergeSummaries(items: SessionSummary[]) {
    const indexed = new Map(sessions.value.map(item => [item.session_id, item]))
    items.forEach(item => { if (!deletedSessionIds.has(item.session_id)) indexed.set(item.session_id, item) })
    sessions.value = [...indexed.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.session_id.localeCompare(a.session_id))
  }
  async function loadMoreSessions() {
    if (deleting.value || loadingHistory.value || !listCursor.value) return
    const current = generation
    const version = historyVersion
    loadingHistory.value = true
    try {
      const page = await api.listSessions({ cursor: listCursor.value }, controller.signal)
      if (current !== generation || version !== historyVersion) return
      mergeSummaries(page.items)
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
      sending.value = false; uploading.value = false
      remember(PENDING_KEY, null)
      receive(view)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      restore(previousId)
      fail(reason)
      retryable.value = true
      retryAction = 'create'
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
      if (reason instanceof ApiError && reason.status === 404) invalidateSession(id)
      error.value = reason instanceof ApiError && reason.status === 404
        ? '这段会话不存在。当前对话与输入仍保留。'
        : reason instanceof Error ? reason.message : '切换对话失败，请重试。'
      retryable.value = !(reason instanceof ApiError && reason.status === 404)
      retryAction = retryable.value ? 'switch' : null
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
    const body = { content: draft.value.trim() ? draft.value : '请查看我上传的文件。', file_ids: [...selectedFileIds.value] }
    if (pending && (pending.content !== body.content || JSON.stringify(pending.file_ids) !== JSON.stringify(body.file_ids))) {
      error.value = '上一条消息的发送状态尚未确认，请先重试，或新建对话。'
      return
    }
    // 断网或 5xx 可能发生在服务接收之后，重试必须沿用同一个消息标识。
    pending ??= { client_message_id: crypto.randomUUID(), ...body }
    const submittedId = pending.client_message_id
    remember(PENDING_KEY, pending.client_message_id)
    sending.value = true
    error.value = ''
    try {
      const run = await api.sendSessionMessage(id, pending, controller.signal)
      if (current !== generation) return
      pending = null; remember(PENDING_KEY, null); retryable.value = false
      draft.value = ''; selectedFileIds.value = []; activeRun.value = run
      const view = await api.getSession(id, {}, controller.signal)
      if (current !== generation) return
      if (!await receiveLatest(view, current)) return
      watchRun(id, run.run_id, current)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      fail(reason)
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 408) {
        pending = null; remember(PENDING_KEY, null)
      }
      retryable.value = true
      retryAction = activeRun.value?.client_message_id === submittedId ? 'stream' : 'send'
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
      if (current !== generation || id !== sessionId.value || run.run_id !== activeRun.value?.run_id) return
      if (isTerminal(result.status)) finishRun(id, result, current)
      else {
        acceptRun(result)
        if (!unsubscribe) watchRun(id, run.run_id, current)
      }
    } catch (reason) { if (current === generation) fail(reason) }
  }
  async function retry() {
    if (deleting.value) return
    const action = retryAction
    if (action === 'create') { await newSession(); return }
    error.value = ''; retryable.value = false
    retryAction = null
    if (action === 'initialize') await initialize()
    else if (action === 'switch' && retryTarget) await switchSession(retryTarget)
    else if (action === 'stream' && activeRun.value && sessionId.value) watchRun(sessionId.value, activeRun.value.run_id, generation)
    else if (action === 'refresh' && activeRun.value && sessionId.value) await refreshCompleted(sessionId.value, activeRun.value.run_id, generation, subscriptionVersion)
    else if (action === 'send' || pending) await send()
    else if (activeRun.value && sessionId.value) watchRun(sessionId.value, activeRun.value.run_id, generation)
  }
  function suspend() {
    suspended = true
    deletionVersion += 1
    deletionController.abort()
    deleting.value = false
    saveCurrent()
    resetRequests()
    initializing.value = false
  }
  onBeforeUnmount(suspend)
  return { sessionId, sessions, messages, files, selectedFileIds, draft, activeRun, streamingText, busy,
    deleting, canDelete, pendingDeletions, deletionError, deleteSession, retryDeletion, hasDraft,
    initializing, uploading, error, retryable, initialize, send, upload, stop, newSession, switchSession, suspend, retry,
    loadMoreSessions, loadEarlierMessages, hasMoreSessions, hasEarlierMessages, loadingHistory, loadingEarlier }
}
