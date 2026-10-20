import { computed, onBeforeUnmount, ref } from 'vue'
import * as api from '../../api/conversations'
import { ApiError } from '../../api/client'
import { isTerminal } from './types'
import type { ConversationView, DocumentView, MessageCreate, MessageView, RunView } from './types'

const SESSION_KEY = 'agent-platform-conversation'
const PENDING_KEY = 'agent-platform-conversation-pending-id'

export function useConversation() {
  const conversationId = ref<string | null>(null)
  const messages = ref<MessageView[]>([])
  const documents = ref<DocumentView[]>([])
  const selectedDocumentIds = ref<string[]>([])
  const draft = ref('')
  const activeRun = ref<RunView | null>(null)
  const error = ref('')
  const initializing = ref(false)
  const sending = ref(false)
  const uploading = ref(false)
  const retryable = ref(false)
  let pending: MessageCreate | null = null
  let retryAction: 'initialize' | 'create' | 'send' | 'poll' | null = null
  let generation = 0
  let controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const busy = computed(() => initializing.value || sending.value || uploading.value ||
    Boolean(activeRun.value && !isTerminal(activeRun.value.status)))

  function remember(key: string, value: string | null) {
    try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value) } catch { /* storage may be disabled */ }
  }
  function stored(key: string) {
    try { return sessionStorage.getItem(key) } catch { return null }
  }
  function merge(incoming: MessageView[]) {
    const indexed = new Map(messages.value.map(message => [message.id, message]))
    incoming.forEach(message => indexed.set(message.id, message))
    messages.value = [...indexed.values()].sort((a, b) => a.sequence - b.sequence)
  }
  function receive(view: ConversationView) {
    conversationId.value = view.id
    remember(SESSION_KEY, view.id)
    merge(view.messages)
    documents.value = view.documents
  }
  function fail(reason: unknown) {
    if (reason instanceof ApiError && reason.status === 404) {
      error.value = '这个临时会话已失效，请新建对话。你的输入仍保留在输入框中。'
      remember(SESSION_KEY, null)
    } else error.value = reason instanceof Error ? reason.message : '操作未完成，请稍后重试。'
  }
  function resetRequests() {
    generation += 1
    controller.abort()
    controller = new AbortController()
    if (timer) clearTimeout(timer)
    timer = undefined
    sending.value = false
    uploading.value = false
    retryable.value = false
    retryAction = null
    return generation
  }
  async function poll(id: string, runId: string, current: number) {
    try {
      const run = await api.getConversationRun(id, runId, controller.signal)
      if (current !== generation) return
      activeRun.value = run
      if (run.message) merge([run.message])
      if (isTerminal(run.status)) {
        if (run.error) error.value = run.error.message
        const view = await api.getConversation(id, 0, controller.signal)
        if (current !== generation) return
        receive(view)
        retryable.value = false
        retryAction = null
        return
      }
      timer = setTimeout(() => void poll(id, runId, current), document.hidden ? 5000 : 1000)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      fail(reason)
      retryable.value = !(reason instanceof ApiError && reason.status === 404)
      retryAction = retryable.value ? 'poll' : null
    }
  }
  async function initialize() {
    const current = resetRequests()
    initializing.value = true
    error.value = ''
    try {
      const id = stored(SESSION_KEY)
      const view = id ? await api.getConversation(id, 0, controller.signal) :
        await api.createConversation(controller.signal)
      if (current !== generation) return
      receive(view)
      remember(PENDING_KEY, null)
      if (view.active_run_id) void poll(view.id, view.active_run_id, current)
    } catch (reason) {
      if (current === generation && !controller.signal.aborted) {
        fail(reason)
        retryable.value = true
        retryAction = reason instanceof ApiError && reason.status === 404 ? 'create' : 'initialize'
      }
    }
    finally { if (current === generation) initializing.value = false }
  }
  async function newConversation() {
    const previousId = conversationId.value
    const current = resetRequests()
    initializing.value = true
    error.value = ''
    try {
      const view = await api.createConversation(controller.signal)
      if (current !== generation) return
      messages.value = []; documents.value = []; selectedDocumentIds.value = []
      activeRun.value = null; pending = null; retryable.value = false
      sending.value = false; uploading.value = false
      remember(PENDING_KEY, null)
      receive(view)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      fail(reason)
      retryable.value = true
      retryAction = 'create'
      // 新会话创建失败时恢复原会话的实际状态，避免旧请求的标记永久禁用输入。
      if (previousId) {
        try {
          const previous = await api.getConversation(previousId, 0, controller.signal)
          if (current !== generation) return
          receive(previous)
          activeRun.value = null
          if (previous.active_run_id) void poll(previousId, previous.active_run_id, current)
        } catch { /* 保留创建失败提示，仍可再次新建 */ }
      }
    }
    finally { if (current === generation) initializing.value = false }
  }
  async function send() {
    const id = conversationId.value
    if (!id || busy.value || !draft.value.trim()) return
    const current = generation
    const body = { content: draft.value, document_ids: [...selectedDocumentIds.value] }
    if (pending && (pending.content !== body.content || JSON.stringify(pending.document_ids) !== JSON.stringify(body.document_ids))) {
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
      const run = await api.sendConversationMessage(id, pending, controller.signal)
      if (current !== generation) return
      pending = null; remember(PENDING_KEY, null); retryable.value = false
      draft.value = ''; activeRun.value = run
      const view = await api.getConversation(id, 0, controller.signal)
      if (current !== generation) return
      receive(view)
      void poll(id, run.id, current)
    } catch (reason) {
      if (current !== generation || controller.signal.aborted) return
      fail(reason)
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 408) {
        pending = null; remember(PENDING_KEY, null)
      }
      retryable.value = true
      retryAction = activeRun.value?.client_message_id === submittedId ? 'poll' : 'send'
    } finally { if (current === generation) sending.value = false }
  }
  async function upload(file: File) {
    const id = conversationId.value
    if (!id || busy.value) return
    const current = generation
    uploading.value = true; error.value = ''
    try {
      const result = await api.uploadConversationDocument(id, file, controller.signal)
      if (current !== generation) return
      documents.value.push(result)
      selectedDocumentIds.value.push(result.id)
    } catch (reason) { if (current === generation && !controller.signal.aborted) fail(reason) }
    finally { if (current === generation) uploading.value = false }
  }
  async function stop() {
    const id = conversationId.value, run = activeRun.value, current = generation
    if (!id || !run || isTerminal(run.status)) return
    try {
      const result = await api.cancelConversationRun(id, run.id)
      if (current !== generation) return
      if (timer) clearTimeout(timer)
      activeRun.value = result
      if (result.message) merge([result.message])
    } catch (reason) { if (current === generation) fail(reason) }
  }
  async function retry() {
    const action = retryAction
    error.value = ''; retryable.value = false
    retryAction = null
    if (action === 'create') await newConversation()
    else if (action === 'initialize') await initialize()
    else if (action === 'send' || pending) await send()
    else if (activeRun.value && conversationId.value) await poll(conversationId.value, activeRun.value.id, generation)
  }
  onBeforeUnmount(() => { resetRequests() })
  return { conversationId, messages, documents, selectedDocumentIds, draft, activeRun, busy,
    initializing, uploading, error, retryable, initialize, send, upload, stop, newConversation, retry }
}
