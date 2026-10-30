// Uses Node's built-in runner and already installed Vue/TypeScript; no test framework dependency.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
const vue = require('vue')

class ApiError extends Error {
  constructor(status, code) { super('simulated request failure'); this.status = status; this.code = code }
}
async function openInitialSession(f) {
  await f.hook.initialize()
  if (!f.hook.sessionId.value && !f.hook.retryable.value) await f.hook.newSession()
}
function fixture(overrides = {}, initialStorage = []) {
  const storage = new Map(initialStorage)
  global.sessionStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  global.document = { hidden: false }
  const view = { session_id: 'c1', messages: [], files: [], active_run_id: null, last_sequence: 0 }
  const completed = id => ({ run_id: id, status: 'succeeded', stage: 'done', message: null, error: null })
  const calls = []
  const api = {
    listSessions: async () => ({ items: [], next_cursor: null }),
    createSession: async () => structuredClone(view),
    deleteSession: async () => {},
    getSession: async () => structuredClone(view),
    sendSessionMessage: async (_id, payload) => {
      calls.push({ ...payload })
      return completed(`r${calls.length}`)
    },
    getSessionRun: async (_id, id) => completed(id),
    uploadSessionFile: async () => {
      const document = { file_id: 'd1', original_name: 'draft.docx', size_bytes: 10, content_chars: 10, created_at: "2026-10-01T00:00:00Z" }
      view.files.push(document)
      return document
    },
    ...overrides,
  }
  for (const method of ['createSession', 'getSession']) {
    const original = api[method]
    api[method] = async (...args) => ({ title: '新对话', agent_id: 'conversation_assistant',
      created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
      has_more: false, next_before_sequence: null, next_after_sequence: null,
      ...await original(...args) })
  }
  const cleanup = []
  const subscriptions = []
  api.subscribeSessionRun ??= (id, runId, handlers, signal) => {
    const subscription = { id, runId, handlers, closed: false }
    subscriptions.push(subscription)
    const close = () => { subscription.closed = true }
    signal?.addEventListener('abort', close, { once: true })
    queueMicrotask(async () => {
      try {
        const run = await api.getSessionRun(id, runId, signal)
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

test('empty history stays empty across initialization and activation', async () => {
  let created = 0
  const f = fixture({ createSession: async () => { created++; return { session_id: 'c1', messages: [], files: [], active_run_id: null, last_sequence: 0 } } })
  try {
    await f.hook.initialize()
    f.hook.suspend()
    await f.hook.initialize()
    assert.equal(f.hook.sessionId.value, null)
    assert.deepEqual(f.hook.sessions.value, [])
    assert.equal(created, 0)
    await f.hook.newSession()
    assert.equal(f.hook.sessionId.value, 'c1')
    assert.equal(created, 1)
  } finally { f.cleanup() }
})

test('delete API accepts an empty 204 response', async () => {
  const f = streamApiFixture()
  const previous = global.fetch
  let request
  global.fetch = async (url, init) => { request = { url, ...init }; return { ok: true, status: 204, json: () => { throw Error('204 must not parse JSON') } } }
  try {
    const controller = new AbortController()
    assert.equal(await f.api.deleteSession('a/b', controller.signal), undefined)
    assert.equal(request.method, 'DELETE')
    assert.equal(request.url, '/api/v1/sessions/a%2Fb')
    assert.equal(request.signal, controller.signal)
  } finally { global.fetch = previous; f.cleanup() }
})

test('initialization restores server history instead of creating an empty conversation', async () => {
  let created = 0
  const view = { session_id: 'saved', title: 'Saved title', agent_id: 'conversation_assistant',
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    messages: [], files: [], active_run_id: null, last_sequence: 0, has_more: false }
  const f = fixture({ listSessions: async () => ({ items: [view], next_cursor: null }),
    getSession: async () => view, createSession: async () => { created++; return view } })
  try {
    await openInitialSession(f)
    assert.equal(created, 0)
    assert.equal(f.hook.sessionId.value, 'saved')
    assert.equal(f.hook.sessions.value[0].title, 'Saved title')
  } finally { f.cleanup() }
})

test('repeated new conversation clicks reuse the current blank conversation', async () => {
  let created = 0
  const f = fixture({ createSession: async () => ({
    session_id: 'c' + (++created), messages: [], files: [], active_run_id: null, last_sequence: 0,
  }) })
  try {
    await openInitialSession(f)
    await f.hook.newSession()
    await f.hook.newSession()
    assert.equal(created, 1)
    assert.equal(f.hook.sessionId.value, 'c1')
    assert.deepEqual(f.hook.sessions.value.map(item => item.session_id), ['c1'])
  } finally { f.cleanup() }
})

test('new conversation clicks while creation is pending do not create extra sessions', async () => {
  let created = 0
  const responses = []
  const view = id => ({ session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({ createSession: () => {
    const id = 'c' + (++created)
    if (created === 1) return view(id)
    return new Promise(resolve => responses.push(() => resolve(view(id))))
  } })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'keep this draft'
    const first = f.hook.newSession()
    const second = f.hook.newSession()
    responses.forEach(resolve => resolve())
    await Promise.all([first, second])
    assert.equal(created, 2)
    assert.equal(f.hook.sessionId.value, 'c2')
    assert.deepEqual(f.hook.sessions.value.map(item => item.session_id), ['c2', 'c1'])
    assert.equal(f.hook.draft.value, '')
  } finally { f.cleanup() }
})

test('missing restored blank conversation becomes empty without creating a replacement', async () => {
  let created = 0
  const f = fixture({
    createSession: async () => ({ session_id: 'c' + (++created), messages: [], files: [], active_run_id: null, last_sequence: 0 }),
    getSession: async () => { throw new ApiError(404) },
  })
  try {
    await openInitialSession(f)
    await f.hook.initialize()
    assert.equal(f.hook.retryable.value, false)
    assert.equal(f.hook.sessionId.value, null)
    assert.equal(f.storage.get('agent-platform-session'), undefined)
    assert.equal(created, 1)
    assert.equal(f.hook.error.value, '')
  } finally { f.cleanup() }
})

for (const content of ['draft', 'file']) {
  test(`new conversation preserves a previous conversation containing only a ${content}`, async () => {
    let created = 0
    const view = id => ({ session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 })
    const f = fixture({ createSession: async () => view('c' + (++created)), getSession: async id => view(id) })
    try {
      await openInitialSession(f)
      if (content === 'draft') f.hook.draft.value = 'unsent draft'
      else await f.hook.upload({ name: 'draft.docx' })
      await f.hook.newSession()
      assert.equal(f.hook.sessionId.value, 'c2')
      assert.equal(f.hook.draft.value, '')
      assert.deepEqual(f.hook.selectedFileIds.value, [])
      await f.hook.switchSession('c1')
      if (content === 'draft') assert.equal(f.hook.draft.value, 'unsent draft')
      else assert.deepEqual(f.hook.selectedFileIds.value, ['d1'])
    } finally { f.cleanup() }
  })
}

test('returning to a cached conversation fills the gap before the latest page', async () => {
  const messages = (start, end) => Array.from({ length: end - start + 1 }, (_, i) => ({
    message_id: `m${start + i}`, sequence: start + i, role: 'user', content: String(start + i), file_ids: [],
  }))
  let created = 0
  const base = id => ({ session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({ createSession: async () => ++created === 1
    ? { ...base('c1'), messages: messages(1, 10), last_sequence: 10 }
    : base('c2'),
  getSession: async (id, options) => {
    if (options?.afterSequence === 10) return { ...base(id), messages: messages(11, 60), has_more: true, next_after_sequence: 60, last_sequence: 100 }
    if (options?.afterSequence === 60) return { ...base(id), messages: messages(61, 100), has_more: false, last_sequence: 100 }
    return { ...base(id), messages: messages(51, 100), last_sequence: 100, has_more: true, next_before_sequence: 51 }
  } })
  try {
    await openInitialSession(f)
    await f.hook.newSession()
    await f.hook.switchSession('c1')
    assert.deepEqual(f.hook.messages.value.map(m => m.sequence), Array.from({ length: 100 }, (_, i) => i + 1))
  } finally { f.cleanup() }
})

test('older message pages stay merged when completion catches up across multiple pages', async () => {
  const message = n => ({ message_id: `m${n}`, sequence: n, role: 'user', content: String(n), file_ids: [] })
  const view = { session_id: 'c1', title: 'First title', agent_id: 'conversation_assistant',
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    files: [], active_run_id: null, last_sequence: 100, messages: [message(50)],
    has_more: true, next_before_sequence: 50 }
  const positions = []
  const f = fixture({ createSession: async () => view,
    getSession: async (_id, options) => {
      positions.push(options)
      if (options?.beforeSequence) return { ...view, messages: [message(1)], has_more: false }
      if (options?.afterSequence === 50) return { ...view, messages: [message(51)], has_more: true, next_after_sequence: 51 }
      return { ...view, messages: [message(100)], has_more: false }
    } })
  try {
    await openInitialSession(f)
    await f.hook.loadEarlierMessages()
    f.hook.activeRun.value = { run_id: 'r1', client_message_id: 'x', status: 'running', stage: '' }
    f.hook.retry()
    await flush()
    assert.deepEqual(f.hook.messages.value.map(m => m.sequence), [1, 50, 51, 100])
    assert.ok(positions.some(p => p.afterSequence === 51))
  } finally { f.cleanup() }
})
async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve() }

function deletionFixture(overrides = {}, initialStorage = []) {
  const views = new Map()
  let count = 0
  const f = fixture({
    createSession: async () => {
      const id = 'c' + (++count)
      const view = { session_id: id, title: id, agent_id: 'conversation_assistant', created_at: `2026-10-01T00:00:0${count}Z`, updated_at: `2026-10-01T00:00:0${count}Z`, messages: [], files: [], active_run_id: null, last_sequence: 0 }
      views.set(id, view)
      return structuredClone(view)
    },
    listSessions: async () => ({ items: [...views.values()].reverse(), next_cursor: null }),
    getSession: async id => { if (!views.has(id)) throw new ApiError(404, 'CONVERSATION_NOT_FOUND'); return structuredClone(views.get(id)) },
    deleteSession: async id => { views.delete(id) },
    ...overrides,
  }, initialStorage)
  return { ...f, views }
}

test('deleting current session restores latest remaining draft', async () => {
  const f = deletionFixture()
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'first draft'
    await f.hook.newSession()
    f.hook.draft.value = 'second draft'
    await f.hook.switchSession('c1')
    assert.equal(f.hook.hasDraft('c2'), true)
    await f.hook.deleteSession('c1')
    assert.equal(f.hook.sessionId.value, 'c2')
    assert.equal(f.hook.draft.value, 'second draft')
    assert.deepEqual(f.hook.sessions.value.map(s => s.session_id), ['c2'])
    assert.deepEqual(f.hook.pendingDeletions.value, [])
  } finally { f.cleanup() }
})

test('deleting last loaded item reloads server first page and remains empty if no history', async () => {
  const f = deletionFixture()
  try {
    await openInitialSession(f)
    f.views.set('c3', { ...f.views.get('c1'), session_id: 'c3', title: 'remaining' })
    await f.hook.deleteSession('c1')
    assert.equal(f.hook.sessionId.value, 'c3')
    await f.hook.deleteSession('c3')
    assert.equal(f.hook.sessionId.value, null)
    assert.deepEqual(f.hook.sessions.value, [])
    assert.equal(f.hook.hasMoreSessions.value, false)
    await f.hook.initialize()
    assert.equal(f.hook.sessionId.value, null)
  } finally { f.cleanup() }
})

test('deleting another session preserves active SSE and draft', async () => {
  let handlers, closed = 0
  const run = { run_id: 'r1', client_message_id: '', status: 'running', message: null, error: null }
  const f = deletionFixture({
    sendSessionMessage: async (_id, body) => { run.client_message_id = body.client_message_id; return run },
    subscribeSessionRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => closed++ },
  })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'keep first'
    await f.hook.newSession()
    await f.hook.switchSession('c1')
    await f.hook.send()
    f.hook.draft.value = 'next draft'
    await f.hook.deleteSession('c2')
    handlers.onEvent({ event: 'delta', text: 'reply' })
    assert.equal(f.hook.sessionId.value, 'c1')
    assert.equal(f.hook.draft.value, 'next draft')
    assert.equal(f.hook.streamingText.value, 'reply')
    assert.equal(closed, 0)
  } finally { f.cleanup() }
})

test('late history callbacks cannot resurrect deleted session', async () => {
  let finish
  const f = deletionFixture()
  try {
    await openInitialSession(f)
    f.api.listSessions = async options => options.cursor ? new Promise(resolve => { finish = resolve }) : ({ items: [...f.views.values()], next_cursor: 'older' })
    await f.hook.initialize()
    const deleted = { ...f.views.get('c1'), session_id: 'c2' }
    f.views.set('c2', deleted)
    const older = f.hook.loadMoreSessions()
    await f.hook.deleteSession('c2')
    finish({ items: [deleted], next_cursor: null })
    await older
    assert.equal(f.hook.sessions.value.some(s => s.session_id === 'c2'), false)
  } finally { f.cleanup() }
})

test('multiple deletion targets survive refresh independently', async () => {
  const f = deletionFixture({ deleteSession: async id => { throw new ApiError(503, id === 'c1' ? 'STORAGE_UNAVAILABLE' : 'CONVERSATION_DELETE_INCOMPLETE') } })
  let seed
  try {
    await openInitialSession(f)
    await f.hook.deleteSession('c1')
    await f.hook.deleteSession('c2')
    assert.deepEqual(f.hook.pendingDeletions.value, [
      { session_id: 'c1', phase: 'unconfirmed' }, { session_id: 'c2', phase: 'cleanup_pending' },
    ])
    seed = [...f.storage]
  } finally { f.cleanup() }
  const next = deletionFixture({}, seed)
  try {
    assert.equal(next.hook.pendingDeletions.value.length, 2)
    await next.hook.initialize()
    await next.hook.retryDeletion('c1')
    assert.equal(next.hook.pendingDeletions.value.length, 1)
    await next.hook.retryDeletion('c2')
    assert.deepEqual(next.hook.pendingDeletions.value, [])
    assert.equal(next.calls.length, 0)
  } finally { next.cleanup() }
})

test('deletion outcomes distinguish busy incomplete and unconfirmed', async () => {
  const f = deletionFixture()
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'keep input'
    f.api.deleteSession = async () => { throw new ApiError(409, 'CONVERSATION_BUSY') }
    await f.hook.deleteSession('c1')
    assert.equal(f.hook.draft.value, 'keep input')
    assert.deepEqual(f.hook.pendingDeletions.value, [])
    f.api.deleteSession = async () => { f.views.delete('c1'); throw new ApiError(503, 'CONVERSATION_DELETE_INCOMPLETE') }
    await f.hook.deleteSession('c1')
    assert.equal(f.hook.sessionId.value, null)
    assert.equal(f.hook.draft.value, '')
    assert.equal(f.hook.pendingDeletions.value[0].phase, 'cleanup_pending')
  } finally { f.cleanup() }
})

test('deletion request serializes page actions and survives suspension', async () => {
  let finish, deleted = 0, reads = 0
  const f = deletionFixture({ deleteSession: async (_id, signal) => {
    deleted++
    return new Promise((resolve, reject) => {
      finish = resolve
      signal.addEventListener('abort', () => reject(new ApiError(0)), { once: true })
    })
  } })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'draft'
    const pending = f.hook.deleteSession('c1')
    await f.hook.deleteSession('c1')
    f.api.getSession = async () => { reads++; throw Error('should not switch') }
    await f.hook.newSession(); await f.hook.switchSession('c2'); await f.hook.send(); await f.hook.upload({ name: 'x.docx' })
    assert.equal(f.hook.deleting.value, true)
    assert.equal(reads, 0)
    assert.equal(deleted, 1)
    assert.equal(f.calls.length, 0)
    f.hook.suspend()
    finish()
    await pending
    assert.equal(f.hook.pendingDeletions.value[0].phase, 'unconfirmed')
  } finally { f.cleanup() }
})

test('old deletion refresh cannot unlock a newer deletion', async () => {
  const f = deletionFixture()
  let finishOldList, finishNewDelete
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'first draft'
    await f.hook.newSession()
    await f.hook.switchSession('c1')
    f.api.listSessions = () => new Promise(resolve => { finishOldList = resolve })
    const old = f.hook.deleteSession('c1')
    await flush()
    assert.equal(typeof finishOldList, 'function')
    f.hook.suspend()
    f.api.listSessions = async () => ({ items: [...f.views.values()], next_cursor: null })
    await f.hook.initialize()
    f.api.deleteSession = id => new Promise(resolve => { finishNewDelete = () => { f.views.delete(id); resolve() } })
    const next = f.hook.deleteSession('c2')
    finishOldList({ items: [], next_cursor: null })
    await old
    assert.equal(f.hook.deleting.value, true)
    assert.equal(f.hook.canDelete.value, false)
    finishNewDelete()
    await next
  } finally { f.cleanup() }
})

for (const phase of ['success', 'cleanup_pending']) {
  test(`known ${phase} after suspension still clears target cache`, async () => {
    const f = deletionFixture()
    let finish
    try {
      await openInitialSession(f)
      f.hook.draft.value = 'first draft'
      await f.hook.newSession()
      f.hook.draft.value = 'second draft'
      await f.hook.switchSession('c1')
      f.api.deleteSession = () => new Promise((resolve, reject) => {
        finish = () => {
          f.views.delete('c2')
          if (phase === 'success') resolve()
          else reject(new ApiError(503, 'CONVERSATION_DELETE_INCOMPLETE'))
        }
      })
      const request = f.hook.deleteSession('c2')
      f.hook.suspend()
      finish()
      await request
      assert.equal(f.hook.hasDraft('c2'), false)
      assert.equal(f.hook.sessionId.value, 'c1')
      assert.equal(f.hook.draft.value, 'first draft')
      assert.deepEqual(f.hook.pendingDeletions.value, phase === 'success' ? [] : [{ session_id: 'c2', phase }])
      await f.hook.initialize()
      assert.equal(f.hook.hasDraft('c2'), false)
    } finally { f.cleanup() }
  })
}

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
    f.api.subscribeSessionRun('会话', 'r1', handlers, controller.signal)
    const source = f.sources[0]
    assert.ok(source.url.endsWith('/runs/r1/events'))
    source.onerror(); source.onerror()
    assert.equal(source.closed, false); assert.equal(reconnects.length, 2)
    source.emit('snapshot', { event: 'snapshot', run: { run_id: 'r1', status: 'running' }, text: '你好' })
    source.onerror(); source.onerror()
    assert.equal(source.closed, false)
    source.onerror()
    assert.equal(source.closed, true); assert.equal(errors.length, 1)
    source.emit('delta', { event: 'delta', text: 'late' })
    assert.equal(events.length, 1)
    f.api.subscribeSessionRun('c1', 'r2', handlers, controller.signal)
    controller.abort()
    assert.equal(f.sources[1].closed, true)
    f.api.subscribeSessionRun('c1', 'r3', handlers)
    f.sources[2].emit('done', { event: 'done', run: { run_id: 'r3', status: 'succeeded' } })
    assert.equal(f.sources[2].closed, true)
    assert.equal(events.at(-1).event, 'done')
    f.api.subscribeSessionRun('c1', 'r4', handlers)
    f.sources[3].emit('delta', 'invalid json')
    assert.equal(f.sources[3].closed, true); assert.equal(errors.length, 2)
  } finally { f.cleanup() }
})

test('SSE deltas appear before completion and reconnect snapshots replace partial text', async () => {
  let handlers, closed = 0
  const run = { run_id: 'r1', client_message_id: '', status: 'running', stage: 'answering', message: null, error: null }
  const f = fixture({
    sendSessionMessage: async (_id, body) => { run.client_message_id = body.client_message_id; return run },
    subscribeSessionRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => closed++ },
  })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'hello'
    await f.hook.send()
    handlers.onEvent({ event: 'snapshot', run, text: '你' })
    handlers.onEvent({ event: 'delta', text: '好' })
    assert.equal(f.hook.streamingText.value, '你好')
    assert.equal(f.hook.busy.value, true)
    handlers.onEvent({ event: 'snapshot', run, text: '你好，' })
    handlers.onEvent({ event: 'delta', text: '世界' })
    assert.equal(f.hook.streamingText.value, '你好，世界')
    const message = { message_id: 'reply', sequence: 2, role: 'assistant', content: '你好，世界', file_ids: [] }
    handlers.onEvent({ event: 'done', run: { ...run, status: 'succeeded', message } })
    await flush()
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(f.hook.messages.value.filter(m => m.message_id === 'reply').length, 1)
    assert.equal(f.hook.busy.value, false)
    assert.equal(closed, 1)
  } finally { f.cleanup() }
})

test('a detached SSE cannot append to another conversation and reconnect never resubmits', async () => {
  let handlers, closed = 0, created = 0
  const f = fixture({
    createSession: async () => ({ session_id: 'c' + (++created), messages: [], files: [], active_run_id: null }),
    sendSessionMessage: async (_id, body) => ({ run_id: 'r1', client_message_id: body.client_message_id, status: 'running', message: null, error: null }),
    subscribeSessionRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => closed++ },
  })
  try {
    await openInitialSession(f); f.hook.draft.value = 'hello'; await f.hook.send()
    const detached = handlers
    await f.hook.newSession()
    detached.onEvent({ event: 'delta', text: 'late' })
    assert.equal(f.hook.sessionId.value, 'c2')
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(closed, 1)
  } finally { f.cleanup() }
})

test('SSE connection failure uses one status read and retry subscribes without resending', async () => {
  let handlers, subscriptions = 0, reads = 0, sends = 0
  const run = { run_id: 'r1', client_message_id: '', status: 'running', stage: 'working', message: null, error: null }
  const f = fixture({
    sendSessionMessage: async (_id, body) => { sends++; run.client_message_id = body.client_message_id; return run },
    subscribeSessionRun: (_id, _runId, callbacks) => { subscriptions++; handlers = callbacks; return () => {} },
    getSessionRun: async () => { reads++; return run },
  })
  try {
    await openInitialSession(f); f.hook.draft.value = 'hello'; await f.hook.send()
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
    getSession: async () => ({ session_id: 'c1', messages: [], files: [], active_run_id: restored ? 'r1' : null }),
    sendSessionMessage: async () => { sends++; throw new ApiError(0) },
    subscribeSessionRun: (_id, _runId, callbacks) => { handlers = callbacks; subscribed++; return () => {} },
    getSessionRun: async () => { throw new ApiError(0) },
  })
  try {
    await openInitialSession(f); f.hook.draft.value = 'hello'; await f.hook.send()
    f.hook.suspend(); restored = true; await openInitialSession(f)
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
  const run = { run_id: 'r1', client_message_id: '', status: 'running', message: null, error: null }
  const final = { message_id: 'final', sequence: 2, role: 'assistant', content: 'complete answer', file_ids: [] }
  const f = fixture({
    getSession: async () => ({ session_id: 'c1', messages: completed ? [final] : [], files: [], active_run_id: completed ? null : 'r1' }),
    sendSessionMessage: async (_id, body) => { run.client_message_id = body.client_message_id; return run },
    subscribeSessionRun: (_id, _runId, callbacks) => { handlers = callbacks; return () => {} },
  })
  try {
    await openInitialSession(f); f.hook.draft.value = 'hello'; await f.hook.send()
    handlers.onEvent({ event: 'snapshot', run, text: 'partial' })
    f.api.createSession = async () => { completed = true; throw new ApiError(0) }
    await f.hook.newSession()
    assert.equal(f.hook.messages.value.some(m => m.message_id === 'final'), true)
    assert.equal(f.hook.streamingText.value, '')
    assert.equal(f.hook.busy.value, false)
  } finally { f.cleanup() }
})

test('a lost response on a later turn retries that submission, not the previous run', async () => {
  const f = fixture()
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'first'
    await f.hook.send(); await flush()
    const original = f.api.sendSessionMessage
    let lose = true
    f.api.sendSessionMessage = async (id, payload) => {
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
    await openInitialSession(f)
    const original = f.api.sendSessionMessage
    let lose = true
    f.api.sendSessionMessage = async (id, payload) => {
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
  const f = fixture({ createSession: async () => {
    if (++attempts === 1) throw new ApiError(0)
    return { session_id: 'c2', messages: [], files: [], active_run_id: null, last_sequence: 0 }
  } })
  try {
    await openInitialSession(f)
    assert.equal(f.hook.retryable.value, true)
    f.hook.retry(); await flush()
    assert.equal(f.hook.sessionId.value, 'c2')
    assert.equal(f.calls.length, 0)
  } finally { f.cleanup() }
})

test('failed new conversation creation releases an aborted upload flag', async () => {
  const f = fixture()
  try {
    await openInitialSession(f)
    f.api.uploadSessionFile = async (_id, _file, signal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
    })
    const uploading = f.hook.upload({ name: 'draft.docx' })
    assert.equal(f.hook.uploading.value, true)
    f.api.createSession = async () => { throw new ApiError(0) }
    await f.hook.newSession()
    await uploading
    assert.equal(f.hook.uploading.value, false)
    assert.equal(f.hook.busy.value, false)
    assert.equal(f.hook.sessionId.value, 'c1')
  } finally { f.cleanup() }
})

test('conversation switching restores its messages, draft and selected files', async () => {
  let created = 0
  const views = {
    c1: { session_id: 'c1', messages: [{ message_id: 'm1', sequence: 1, role: 'user', content: 'first conversation', file_ids: [] }], files: [], active_run_id: null, last_sequence: 1 },
    c2: { session_id: 'c2', messages: [], files: [], active_run_id: null, last_sequence: 0 },
  }
  const f = fixture({ createSession: async () => views[++created === 1 ? 'c1' : 'c2'], getSession: async id => views[id] })
  try {
    await openInitialSession(f)
    await f.hook.upload({ name: 'draft.docx' })
    f.hook.draft.value = 'unsent draft'
    await f.hook.newSession()
    assert.equal(f.hook.messages.value.length, 0)
    assert.equal(f.hook.draft.value, '')
    await f.hook.switchSession('c1')
    assert.equal(f.hook.messages.value[0].content, 'first conversation')
    assert.equal(f.hook.draft.value, 'unsent draft')
    assert.deepEqual([...f.hook.selectedFileIds.value], ['d1'])
    assert.equal(f.hook.sessions.value.length, 2)
  } finally { f.cleanup() }
})

test('accepted attachments leave the composer and are not sent again on the next turn', async () => {
  const f = fixture()
  try {
    await openInitialSession(f)
    await f.hook.upload({ name: 'draft.docx' })
    f.hook.draft.value = 'use this file'
    await f.hook.send(); await flush()
    assert.deepEqual([...f.hook.selectedFileIds.value], [])
    assert.equal(f.hook.files.value.some(d => d.file_id === 'd1'), true)
    f.hook.draft.value = 'continue without attaching again'
    await f.hook.send(); await flush()
    assert.deepEqual(f.calls[0].file_ids, ['d1'])
    assert.deepEqual(f.calls[1].file_ids, [])
  } finally { f.cleanup() }
})

test('switching away after an ambiguous response preserves the original idempotency key', async () => {
  let created = 0
  const view = id => ({ session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({ createSession: async () => view(++created === 1 ? 'c1' : 'c2'), getSession: async id => view(id) })
  try {
    await openInitialSession(f)
    let lost = true
    f.api.sendSessionMessage = async (_id, payload) => {
      f.calls.push({ ...payload })
      if (lost) { lost = false; throw new ApiError(502) }
      return { ...f.completed('r1'), client_message_id: payload.client_message_id }
    }
    f.hook.draft.value = 'possibly accepted'
    await f.hook.send()
    await f.hook.newSession()
    await f.hook.switchSession('c1')
    await f.hook.retry(); await flush()
    assert.equal(f.calls.length, 2)
    assert.equal(f.calls[0].client_message_id, f.calls[1].client_message_id)
    assert.equal(f.calls[1].content, 'possibly accepted')
  } finally { f.cleanup() }
})

test('a failed switch keeps the current conversation and draft', async () => {
  const f = fixture({ getSession: async id => {
    if (id === 'missing') throw new ApiError(404)
    return { session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 }
  } })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'keep this draft'
    await f.hook.switchSession('missing')
    assert.equal(f.hook.sessionId.value, 'c1')
    assert.equal(f.hook.draft.value, 'keep this draft')
    assert.equal(f.storage.get('agent-platform-session'), 'c1')
    assert.equal(f.hook.busy.value, false)
  } finally { f.cleanup() }
})

test('deactivated requests cannot append a late upload to the active conversation', async () => {
  let finishUpload
  const f = fixture({ uploadSessionFile: () => new Promise(resolve => { finishUpload = resolve }) })
  try {
    await openInitialSession(f)
    f.hook.draft.value = 'keep on return'
    const request = f.hook.upload({ name: 'draft.docx' })
    f.hook.suspend()
    finishUpload({ file_id: 'late', original_name: 'late.docx', size_bytes: 20, content_chars: 20, created_at: "2026-10-01T00:00:00Z" })
    await request
    assert.equal(f.hook.files.value.length, 0)
    assert.equal(f.hook.uploading.value, false)
    await openInitialSession(f)
    assert.equal(f.hook.draft.value, 'keep on return')
  } finally { f.cleanup() }
})

test('an attachment can be sent without inventing an empty backend message', async () => {
  const f = fixture()
  try {
    await openInitialSession(f)
    await f.hook.upload({ name: 'draft.docx' })
    await f.hook.send(); await flush()
    assert.equal(f.calls.length, 1)
    assert.equal(f.calls[0].content, '请查看我上传的文件。')
    assert.deepEqual(f.calls[0].file_ids, ['d1'])
  } finally { f.cleanup() }
})

test('stopping during a pending conversation switch cannot write the old run into the new conversation', async () => {
  const view = id => ({ session_id: id, messages: [], files: [], active_run_id: id === 'c1' ? 'r1' : null, last_sequence: 0 })
  const running = { run_id: 'r1', client_message_id: 'client-1', status: 'running', stage: 'working', message: null, error: null }
  let finishSwitch, finishCancel, cancelCalls = 0
  const cancellation = new Promise(resolve => { finishCancel = resolve })
  const f = fixture({
    createSession: async () => view('c1'),
    getSession: async id => id === 'c2' ? new Promise(resolve => { finishSwitch = resolve }) : view(id),
    getSessionRun: async () => running,
    cancelSessionRun: async () => { cancelCalls++; return cancellation },
  })
  try {
    await openInitialSession(f)
    const switching = f.hook.switchSession('c2')
    const stopping = f.hook.stop()
    finishSwitch(view('c2'))
    await switching
    finishCancel({ ...running, status: 'cancelled', message: { message_id: 'old-reply', sequence: 1, role: 'assistant', content: 'old conversation reply', file_ids: [] } })
    await stopping
    assert.equal(f.hook.sessionId.value, 'c2')
    assert.equal(f.hook.activeRun.value, null)
    assert.equal(f.hook.messages.value.length, 0)
    assert.equal(cancelCalls, 0)
  } finally { f.cleanup() }
})

test('a failed switch retry belongs to its own conversation snapshot', async () => {
  let created = 0
  const failures = new Set()
  const requested = []
  const view = id => ({ session_id: id, messages: [], files: [], active_run_id: null, last_sequence: 0 })
  const f = fixture({
    createSession: async () => view('c' + (++created)),
    getSession: async id => { requested.push(id); if (failures.has(id)) throw new ApiError(503); return view(id) },
  })
  try {
    await openInitialSession(f)
    for (let i = 1; i <= 3; i++) {
      f.hook.draft.value = `draft ${i}`
      await f.hook.newSession()
    }
    await f.hook.switchSession('c1')
    failures.add('c2'); failures.add('c4')
    await f.hook.switchSession('c2')
    await f.hook.switchSession('c3')
    await f.hook.switchSession('c4')
    await f.hook.switchSession('c1')
    await f.hook.retry()
    assert.equal(requested.at(-1), 'c2')
    assert.equal(f.hook.sessionId.value, 'c1')
  } finally { f.cleanup() }
})
