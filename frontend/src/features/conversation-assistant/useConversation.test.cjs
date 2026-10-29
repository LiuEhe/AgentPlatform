// Uses Node's built-in runner and already installed Vue/TypeScript; no test framework dependency.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
const vue = require('vue')

class ApiError extends Error {
  constructor(status) { super('simulated request failure'); this.status = status }
}
function fixture(overrides = {}) {
  const storage = new Map()
  global.sessionStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  global.document = { hidden: false }
  const view = { id: 'c1', messages: [], documents: [], active_run_id: null, last_sequence: 0 }
  const completed = id => ({ id, status: 'succeeded', stage: 'done', message: null, error: null })
  const calls = []
  const api = {
    createConversation: async () => structuredClone(view),
    getConversation: async () => structuredClone(view),
    sendConversationMessage: async (_id, payload) => {
      calls.push({ ...payload })
      return completed(`r${calls.length}`)
    },
    getConversationRun: async (_id, id) => completed(id),
    uploadConversationDocument: async () => {
      const document = { id: 'd1', filename: 'draft.docx', chars: 10 }
      view.documents.push(document)
      return document
    },
    ...overrides,
  }
  const cleanup = []
  const subscriptions = []
  api.subscribeConversationRun ??= (id, runId, handlers, signal) => {
    const subscription = { id, runId, handlers, closed: false }
    subscriptions.push(subscription)
    const close = () => { subscription.closed = true }
    signal?.addEventListener('abort', close, { once: true })
    queueMicrotask(async () => {
      try {
        const run = await api.getConversationRun(id, runId, signal)
        if (!subscription.closed) handlers.onEvent({ event: 'snapshot', run, text: '' })
      } catch (reason) { if (!subscription.closed) handlers.onError(reason) }
    })
    return close
  }
  const filename = path.join(__dirname, 'useConversation.ts')
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = module.paths
  loaded.require = id => {
    if (id === 'vue') return { ...vue, onBeforeUnmount: callback => cleanup.push(callback) }
    if (id === '../../api/conversations') return api
    if (id === '../../api/client') return { ApiError }
    if (id === './types') return { isTerminal: status => ['succeeded', 'failed', 'cancelled'].includes(status) }
    return require(id)
  }
  loaded._compile(compiled, filename)
  return { hook: loaded.exports.useConversation(), cleanup: () => cleanup.forEach(fn => fn()), calls, api, completed, storage, subscriptions }
}
async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve() }

function streamApiFixture() {
  const sources = []
  const previous = global.EventSource
  class Source {
    static CLOSED = 2
    readyState = 0
    listeners = new Map()
    closed = false
    constructor(url) { this.url = url; sources.push(this) }
    addEventListener(kind, callback) { this.listeners.set(kind, callback) }
    close() { this.closed = true; this.readyState = 2 }
    emit(kind, data) { this.listeners.get(kind)?.({ data: typeof data === 'string' ? data : JSON.stringify(data) }) }
  }
  global.EventSource = Source
  const filename = path.resolve(__dirname, '../../api/conversations.ts')
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const loaded = new Module(filename, module)
  loaded.filename = filename; loaded.paths = module.paths
  loaded.require = id => {
    if (id === './client') return { ApiError, getApiBaseUrl: () => '' }
    if (id.endsWith('/types')) return { isTerminal: status => ['succeeded', 'failed', 'cancelled'].includes(status) }
    return require(id)
  }
  loaded._compile(compiled, filename)
  return { api: loaded.exports, sources, cleanup: () => { global.EventSource = previous } }
}

test('native EventSource reconnects only within the bound and closes on abort or terminal', () => {
  const f = streamApiFixture()
  const events = [], errors = [], reconnects = []
  const handlers = { onEvent: e => events.push(e), onError: e => errors.push(e), onReconnecting: () => reconnects.push(1) }
  try {
    const controller = new AbortController()
    f.api.subscribeConversationRun('会话', 'r1', handlers, controller.signal)
    const source = f.sources[0]
    assert.ok(source.url.endsWith('/runs/r1/events'))
    source.onerror(); source.onerror()
    assert.equal(source.closed, false); assert.equal(reconnects.length, 2)
    source.emit('snapshot', { event: 'snapshot', run: { id: 'r1', status: 'running' }, text: '你好' })
    source.onerror(); source.onerror()
    assert.equal(source.closed, false)
    source.onerror()
    assert.equal(source.closed, true); assert.equal(errors.length, 1)
    source.emit('delta', { event: 'delta', text: 'late' })
    assert.equal(events.length, 1)
    f.api.subscribeConversationRun('c1', 'r2', handlers, controller.signal)
    controller.abort()
    assert.equal(f.sources[1].closed, true)
    f.api.subscribeConversationRun('c1', 'r3', handlers)
    f.sources[2].emit('done', { event: 'done', run: { id: 'r3', status: 'succeeded' } })
    assert.equal(f.sources[2].closed, true)
    assert.equal(events.at(-1).event, 'done')
    f.api.subscribeConversationRun('c1', 'r4', handlers)
    f.sources[3].emit('delta', 'invalid json')
    assert.equal(f.sources[3].closed, true); assert.equal(errors.length, 2)
  } finally { f.cleanup() }
})

test('SSE deltas appear before completion and reconnect snapshots replace partial text', async () => {
  let handlers, closed = 0
  const run = { id: 'r1', client_message_id: '', status: 'running', stage: 'answering', message: null, error: null }
  const f = fixture({
    sendConversationMessage: async (_id, body) => { run.client_message_id = body.client_message_id; return run },
    subscribeConversationRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => closed++ },
  })
  try {
    await f.hook.initialize()
    f.hook.draft.value = 'hello'
    await f.hook.send()
    handlers.onEvent({ event: 'snapshot', run, text: '你' })
    handlers.onEvent({ event: 'delta', text: '好' })
    assert.equal(f.hook.streamingText.value, '你好')
    assert.equal(f.hook.busy.value, true)
    handlers.onEvent({ event: 'snapshot', run, text: '你好，' })
    handlers.onEvent({ event: 'delta', text: '世界' })
    assert.equal(f.hook.streamingText.value, '你好，世界')
    const message = { id: 'reply', sequence: 2, role: 'assistant', content: '你好，世界', document_ids: [] }
    handlers.onEvent({ event: 'done', run: { ...run, status: 'succeeded', message } })
    await flush()
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(f.hook.messages.value.filter(m => m.id === 'reply').length, 1)
    assert.equal(f.hook.busy.value, false)
    assert.equal(closed, 1)
  } finally { f.cleanup() }
})

test('a detached SSE cannot append to another conversation and reconnect never resubmits', async () => {
  let handlers, closed = 0, created = 0
  const f = fixture({
    createConversation: async () => ({ id: 'c' + (++created), messages: [], documents: [], active_run_id: null }),
    sendConversationMessage: async (_id, body) => ({ id: 'r1', client_message_id: body.client_message_id, status: 'running', message: null, error: null }),
    subscribeConversationRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => closed++ },
  })
  try {
    await f.hook.initialize(); f.hook.draft.value = 'hello'; await f.hook.send()
    const detached = handlers
    await f.hook.newConversation()
    detached.onEvent({ event: 'delta', text: 'late' })
    assert.equal(f.hook.conversationId.value, 'c2')
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(closed, 1)
  } finally { f.cleanup() }
})

test('SSE connection failure uses one status read and retry subscribes without resending', async () => {
  let handlers, subscriptions = 0, reads = 0, sends = 0
  const run = { id: 'r1', client_message_id: '', status: 'running', stage: 'working', message: null, error: null }
  const f = fixture({
    sendConversationMessage: async (_id, body) => { sends++; run.client_message_id = body.client_message_id; return run },
    subscribeConversationRun: (_id, _runId, callbacks) => { subscriptions++; handlers = callbacks; return () => {} },
    getConversationRun: async () => { reads++; return run },
  })
  try {
    await f.hook.initialize(); f.hook.draft.value = 'hello'; await f.hook.send()
    handlers.onError(new ApiError(0)); await flush()
    assert.equal(reads, 1)
    assert.equal(f.hook.retryable.value, true)
    await f.hook.retry()
    assert.equal(subscriptions, 2)
    assert.equal(sends, 1)
  } finally { f.cleanup() }
})

test('retry reconnects an unconfirmed submission even when status recovery also failed', async () => {
  let handlers, subscribed = 0, restored = false, sends = 0
  const f = fixture({
    getConversation: async () => ({ id: 'c1', messages: [], documents: [], active_run_id: restored ? 'r1' : null }),
    sendConversationMessage: async () => { sends++; throw new ApiError(0) },
    subscribeConversationRun: (_id, _runId, callbacks) => { handlers = callbacks; subscribed++; return () => {} },
    getConversationRun: async () => { throw new ApiError(0) },
  })
  try {
    await f.hook.initialize(); f.hook.draft.value = 'hello'; await f.hook.send()
    f.hook.suspend(); restored = true; await f.hook.initialize()
    handlers.onError(new ApiError(0)); await flush()
    assert.equal(f.hook.busy.value, true)
    assert.equal(f.hook.retryable.value, true)
    await f.hook.retry()
    assert.equal(subscribed, 2)
    assert.equal(sends, 1)
  } finally { f.cleanup() }
})

test('failed new conversation restores a completed reply without a stale partial bubble', async () => {
  let handlers, completed = false
  const run = { id: 'r1', client_message_id: '', status: 'running', message: null, error: null }
  const final = { id: 'final', sequence: 2, role: 'assistant', content: 'complete answer', document_ids: [] }
  const f = fixture({
    getConversation: async () => ({ id: 'c1', messages: completed ? [final] : [], documents: [], active_run_id: completed ? null : 'r1' }),
    sendConversationMessage: async (_id, body) => { run.client_message_id = body.client_message_id; return run },
    subscribeConversationRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => {} },
  })
  try {
    await f.hook.initialize(); f.hook.draft.value = 'hello'; await f.hook.send()
    handlers.onEvent({ event: 'snapshot', run, text: 'partial' })
    f.api.createConversation = async () => { completed = true; throw new ApiError(0) }
    await f.hook.newConversation()
    assert.equal(f.hook.messages.value.some(m => m.id === 'final'), true)
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(f.hook.busy.value, false)
  } finally { f.cleanup() }
})

test('a lost response on a later turn retries that submission, not the previous run', async () => {
  const f = fixture()
  try {
    await f.hook.initialize()
    f.hook.draft.value = 'first'
    await f.hook.send(); await flush()
    const original = f.api.sendConversationMessage
    let lose = true
    f.api.sendConversationMessage = async (id, payload) => {
      if (lose) { lose = false; f.calls.push({ ...payload }); throw new ApiError(0) }
      return original(id, payload)
    }
    f.hook.draft.value = 'second'
    await f.hook.send()
    const lostId = f.calls[1].client_message_id
    f.hook.retry(); await flush()
    assert.equal(f.calls.length, 3)
    assert.equal(f.calls[2].content, 'second')
    assert.equal(f.calls[2].client_message_id, lostId)
  } finally { f.cleanup() }
})

test('an ambiguous HTTP 502 preserves the submission idempotency key', async () => {
  const f = fixture()
  try {
    await f.hook.initialize()
    const original = f.api.sendConversationMessage
    let lose = true
    f.api.sendConversationMessage = async (id, payload) => {
      if (lose) { lose = false; f.calls.push({ ...payload }); throw new ApiError(502) }
      return original(id, payload)
    }
    f.hook.draft.value = 'request may already have been accepted'
    await f.hook.send()
    f.hook.retry(); await flush()
    assert.equal(f.calls.length, 2)
    assert.equal(f.calls[0].client_message_id, f.calls[1].client_message_id)
  } finally { f.cleanup() }
})

test('a failed initial connection can be retried without sending a message', async () => {
  let attempts = 0
  const f = fixture({ createConversation: async () => {
    if (++attempts === 1) throw new ApiError(0)
    return { id: 'c2', messages: [], documents: [], active_run_id: null, last_sequence: 0 }
  } })
  try {
    await f.hook.initialize()
    assert.equal(f.hook.retryable.value, true)
    f.hook.retry(); await flush()
    assert.equal(f.hook.conversationId.value, 'c2')
    assert.equal(f.calls.length, 0)
  } finally { f.cleanup() }
})

test('failed new conversation creation releases an aborted upload flag', async () => {
  const f = fixture()
  try {
    await f.hook.initialize()
    f.api.uploadConversationDocument = async (_id, _file, signal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
    })
    const uploading = f.hook.upload({ name: 'draft.docx' })
    assert.equal(f.hook.uploading.value, true)
    f.api.createConversation = async () => { throw new ApiError(0) }
    await f.hook.newConversation()
    await uploading
    assert.equal(f.hook.uploading.value, false)
    assert.equal(f.hook.busy.value, false)
    assert.equal(f.hook.conversationId.value, 'c1')
  } finally { f.cleanup() }
})

test('conversation switching restores its messages, draft and selected documents', async () => {
  let created = 0
  const views = {
    c1: { id: 'c1', messages: [{ id: 'm1', sequence: 1, role: 'user', content: 'first conversation', document_ids: [] }], documents: [], active_run_id: null, last_sequence: 1 },
    c2: { id: 'c2', messages: [], documents: [], active_run_id: null, last_sequence: 0 },
  }
  const f = fixture({ createConversation: async () => views[++created === 1 ? 'c1' : 'c2'], getConversation: async id => views[id] })
  try {
    await f.hook.initialize()
    await f.hook.upload({ name: 'draft.docx' })
    f.hook.draft.value = 'unsent draft'
    await f.hook.newConversation()
    assert.equal(f.hook.messages.value.length, 0)
    assert.equal(f.hook.draft.value, '')
    await f.hook.switchConversation('c1')
    assert.equal(f.hook.messages.value[0].content, 'first conversation')
    assert.equal(f.hook.draft.value, 'unsent draft')
    assert.deepEqual([...f.hook.selectedDocumentIds.value], ['d1'])
    assert.equal(f.hook.conversations.value.length, 2)
  } finally { f.cleanup() }
})

test('accepted attachments leave the composer and are not sent again on the next turn', async () => {
  const f = fixture()
  try {
    await f.hook.initialize()
    await f.hook.upload({ name: 'draft.docx' })
    f.hook.draft.value = 'use this file'
    await f.hook.send(); await flush()
    assert.deepEqual([...f.hook.selectedDocumentIds.value], [])
    assert.equal(f.hook.documents.value.some(d => d.id === 'd1'), true)
    f.hook.draft.value = 'continue without attaching again'
    await f.hook.send(); await flush()
    assert.deepEqual(f.calls[0].document_ids, ['d1'])
    assert.deepEqual(f.calls[1].document_ids, [])
  } finally { f.cleanup() }
})

test('switching away after an ambiguous response preserves the original idempotency key', async () => {
  let created = 0
  const view = id => ({ id, messages: [], documents: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({ createConversation: async () => view(++created === 1 ? 'c1' : 'c2'), getConversation: async id => view(id) })
  try {
    await f.hook.initialize()
    let lost = true
    f.api.sendConversationMessage = async (_id, payload) => {
      f.calls.push({ ...payload })
      if (lost) { lost = false; throw new ApiError(502) }
      return { ...f.completed('r1'), client_message_id: payload.client_message_id }
    }
    f.hook.draft.value = 'possibly accepted'
    await f.hook.send()
    await f.hook.newConversation()
    await f.hook.switchConversation('c1')
    await f.hook.retry(); await flush()
    assert.equal(f.calls.length, 2)
    assert.equal(f.calls[0].client_message_id, f.calls[1].client_message_id)
    assert.equal(f.calls[1].content, 'possibly accepted')
  } finally { f.cleanup() }
})

test('a failed switch keeps the current conversation and draft', async () => {
  const f = fixture({ getConversation: async id => {
    if (id === 'missing') throw new ApiError(404)
    return { id, messages: [], documents: [], active_run_id: null, last_sequence: 0 }
  } })
  try {
    await f.hook.initialize()
    f.hook.draft.value = 'keep this draft'
    await f.hook.switchConversation('missing')
    assert.equal(f.hook.conversationId.value, 'c1')
    assert.equal(f.hook.draft.value, 'keep this draft')
    assert.equal(f.storage.get('agent-platform-conversation'), 'c1')
    assert.equal(f.hook.busy.value, false)
  } finally { f.cleanup() }
})

test('deactivated requests cannot append a late upload to the active conversation', async () => {
  let finishUpload
  const f = fixture({ uploadConversationDocument: () => new Promise(resolve => { finishUpload = resolve }) })
  try {
    await f.hook.initialize()
    f.hook.draft.value = 'keep on return'
    const request = f.hook.upload({ name: 'draft.docx' })
    f.hook.suspend()
    finishUpload({ id: 'late', filename: 'late.docx', chars: 20 })
    await request
    assert.equal(f.hook.documents.value.length, 0)
    assert.equal(f.hook.uploading.value, false)
    await f.hook.initialize()
    assert.equal(f.hook.draft.value, 'keep on return')
  } finally { f.cleanup() }
})

test('an attachment can be sent without inventing an empty backend message', async () => {
  const f = fixture()
  try {
    await f.hook.initialize()
    await f.hook.upload({ name: 'draft.docx' })
    await f.hook.send(); await flush()
    assert.equal(f.calls.length, 1)
    assert.equal(f.calls[0].content, '请查看我上传的文件。')
    assert.deepEqual(f.calls[0].document_ids, ['d1'])
  } finally { f.cleanup() }
})

test('stopping during a pending conversation switch cannot write the old run into the new conversation', async () => {
  const view = id => ({ id, messages: [], documents: [], active_run_id: id === 'c1' ? 'r1' : null, last_sequence: 0 })
  const running = { id: 'r1', client_message_id: 'client-1', status: 'running', stage: 'working', message: null, error: null }
  let finishSwitch, finishCancel, cancelCalls = 0
  const cancellation = new Promise(resolve => { finishCancel = resolve })
  const f = fixture({
    createConversation: async () => view('c1'),
    getConversation: async id => id === 'c2' ? new Promise(resolve => { finishSwitch = resolve }) : view(id),
    getConversationRun: async () => running,
    cancelConversationRun: async () => { cancelCalls++; return cancellation },
  })
  try {
    await f.hook.initialize()
    const switching = f.hook.switchConversation('c2')
    const stopping = f.hook.stop()
    finishSwitch(view('c2'))
    await switching
    finishCancel({ ...running, status: 'cancelled', message: { id: 'old-reply', sequence: 1, role: 'assistant', content: 'old conversation reply', document_ids: [] } })
    await stopping
    assert.equal(f.hook.conversationId.value, 'c2')
    assert.equal(f.hook.activeRun.value, null)
    assert.equal(f.hook.messages.value.length, 0)
    assert.equal(cancelCalls, 0)
  } finally { f.cleanup() }
})

test('a failed switch retry belongs to its own conversation snapshot', async () => {
  let created = 0
  const failures = new Set()
  const requested = []
  const view = id => ({ id, messages: [], documents: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({
    createConversation: async () => view('c' + (++created)),
    getConversation: async id => { requested.push(id); if (failures.has(id)) throw new ApiError(503); return view(id) },
  })
  try {
    await f.hook.initialize()
    await f.hook.newConversation(); await f.hook.newConversation(); await f.hook.newConversation()
    await f.hook.switchConversation('c1')
    failures.add('c2'); failures.add('c4')
    await f.hook.switchConversation('c2')
    await f.hook.switchConversation('c3')
    await f.hook.switchConversation('c4')
    await f.hook.switchConversation('c1')
    await f.hook.retry()
    assert.equal(requested.at(-1), 'c2')
    assert.equal(f.hook.conversationId.value, 'c1')
  } finally { f.cleanup() }
})
