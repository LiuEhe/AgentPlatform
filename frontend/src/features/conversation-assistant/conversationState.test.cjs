const test = require('node:test')
const assert = require('node:assert/strict')
const load = require('./loadConversationModule.cjs')

class ApiError extends Error {
  constructor(status, code) { super('request failed'); this.status = status; this.code = code }
}
function deletionFixture(remove, initial = null) {
  let saved = initial
  const removed = []
  const { createConversationDeletions } = load('conversationDeletions.ts', {
    '../../api/client': { ApiError },
  })
  const state = createConversationDeletions({
    canDelete: () => !state.deleting.value,
    readPending: () => saved,
    writePending: value => { saved = value },
    remove,
    onRemoved: async (id, resume) => { removed.push({ id, resume }) },
  })
  return { state, removed, saved: () => saved }
}

test('snapshots restore isolated draft and attachment selections and invalidate stale retry targets', () => {
  const { ConversationSnapshots } = load('conversationSnapshots.ts')
  const snapshots = new ConversationSnapshots()
  const first = snapshots.restore(null)
  first.draft = 'unsent'
  first.selectedIds.push('file-1')
  first.pending = { client_message_id: 'same-id', content: 'unsent', file_ids: ['file-1'] }
  snapshots.save('c1', first)
  first.selectedIds.length = 0
  const restored = snapshots.restore('c1')
  assert.equal(restored.draft, 'unsent')
  assert.deepEqual(restored.selectedIds, ['file-1'])
  assert.equal(restored.pending.client_message_id, 'same-id')
  restored.selectedIds.push('file-2')
  assert.deepEqual(snapshots.restore('c1').selectedIds, ['file-1'])
  snapshots.save('c2', { ...snapshots.restore(null), retryAction: 'switch', retryTarget: 'c1' })
  snapshots.invalidate('c1')
  assert.equal(snapshots.restore('c1').draft, '')
  assert.equal(snapshots.restore('c2').retryTarget, null)
  assert.equal(snapshots.restore('c2').retryAction, null)
  snapshots.clear()
  assert.equal(snapshots.hasDraft('c2'), false)
})

test('deletion recovery accepts only valid phases, keeps unknown submissions and retries cleanup with the same id', async () => {
  let attempt = 0
  const ids = []
  const f = deletionFixture(async id => {
    ids.push(id)
    if (++attempt === 1) throw new Error('connection lost')
    if (attempt === 2) throw new ApiError(503, 'CONVERSATION_DELETE_INCOMPLETE')
  }, JSON.stringify([{ session_id: 'bad', phase: 'other' }, { session_id: 'c0', phase: 'unconfirmed' }, { session_id: 'c0', phase: 'cleanup_pending' }]))
  assert.deepEqual(f.state.pendingDeletions.value, [{ session_id: 'c0', phase: 'cleanup_pending' }])
  await f.state.deleteSession('c1')
  assert.equal(f.state.pendingDeletions.value.find(p => p.session_id === 'c1').phase, 'unconfirmed')
  assert.equal(f.removed.length, 0)
  await f.state.retryDeletion('c1')
  assert.equal(f.state.pendingDeletions.value.find(p => p.session_id === 'c1').phase, 'cleanup_pending')
  assert.deepEqual(f.removed, [{ id: 'c1', resume: true }])
  await f.state.retryDeletion('c1')
  assert.deepEqual(ids, ['c1', 'c1', 'c1'])
  assert.equal(JSON.parse(f.saved()).some(p => p.session_id === 'c1'), false)
})

test('suspending retains a confirmed deletion result but prevents navigation; identity clear ignores late completion', async () => {
  let resolve
  const f = deletionFixture(() => new Promise(done => { resolve = done }))
  const pending = f.state.deleteSession('c1')
  f.state.suspend()
  resolve()
  await pending
  assert.deepEqual(f.removed, [{ id: 'c1', resume: false }])
  f.state.resume()
  const next = f.state.deleteSession('c2')
  f.state.clear()
  const persisted = f.saved()
  resolve()
  await next
  assert.deepEqual(f.state.pendingDeletions.value, [])
  assert.equal(f.saved(), persisted)
  assert.equal(f.removed.length, 1)
})
