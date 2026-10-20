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
    createConversation: async () => ({ ...view }),
    getConversation: async () => ({ ...view }),
    sendConversationMessage: async (_id, payload) => {
      calls.push({ ...payload })
      return completed(`r${calls.length}`)
    },
    getConversationRun: async (_id, id) => completed(id),
    uploadConversationDocument: async () => ({ id: 'd1', filename: 'draft.docx', chars: 10 }),
    ...overrides,
  }
  const cleanup = []
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
  return { hook: loaded.exports.useConversation(), cleanup: () => cleanup.forEach(fn => fn()), calls, api, completed, storage }
}
async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve() }

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
