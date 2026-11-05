const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, text, flush, auth, vue } = require('../features/auth/componentTestHarness.cjs')
const Empty = vue.defineComponent({ setup: () => () => vue.h('span') })
const component = value => ({ __esModule: true, default: value })
function documentFixture() {
  const previous = global.document
  const trigger = vue.markRaw({ isConnected: true, focus() { global.document.activeElement = this } })
  global.document = { activeElement: trigger, querySelector: () => trigger }
  return { trigger, restore() { global.document = previous } }
}

test('conversation deletion shares confirmation, preserves drafts on cancel and only deletes its selected target', async () => {
  const document = documentFixture(), calls = []
  const hook = {}
  for (const [key, value] of Object.entries({ sessionId: 'c1', sessions: [{ session_id: 'c1', title: 'hi' }],
    messages: [], files: [], selectedFileIds: [], draft: 'unsent', activeRun: null, streamingText: '', busy: false,
    initializing: false, uploading: false, error: '', retryable: false, deleting: false, canDelete: true,
    pendingDeletions: [], deletionError: '', hasMoreSessions: false, hasEarlierMessages: false, loadingHistory: false, loadingEarlier: false })) hook[key] = vue.ref(value)
  for (const key of ['initialize', 'send', 'upload', 'stop', 'newSession', 'switchSession', 'suspend', 'retry', 'loadMoreSessions', 'loadEarlierMessages', 'retryDeletion']) hook[key] = () => {}
  hook.hasDraft = () => true
  hook.deleteSession = async id => { calls.push(id) }
  const History = vue.defineComponent({ emits: ['delete'], setup: (_, { emit }) => () => vue.h('button', { 'data-delete': 'c1', onClick: () => emit('delete', 'c1') }, '删除') })
  const f = mount('../../views/AgentConversationView.vue', {
    '../features/conversation-assistant/useConversation': { useConversation: () => hook },
    '../features/auth/useAuth': { useAuth: () => auth() },
    '../features/auth/AccountMenu.vue': component(Empty),
    ...Object.fromEntries(['ConversationComposer', 'ConversationMessages', 'ConversationAttachments'].map(name => ['../features/conversation-assistant/' + name + '.vue', component(Empty)])),
    '../features/conversation-assistant/ConversationHistory.vue': component(History),
  })
  try {
    await flush()
    find(f.root, n => n['data-delete'] === 'c1').onClick(); await flush()
    const dialog = find(f.root, n => n.tag === 'dialog' && n['aria-labelledby'] === 'delete-session-title')
    assert.equal(dialog.open, true)
    assert.match(text(dialog), /hi/)
    assert.match(text(dialog), /草稿/)
    find(f.root, n => n.id === 'delete-session-cancel').onClick(); await flush()
    assert.equal(hook.draft.value, 'unsent')
    assert.deepEqual(calls, [])
    const mobile = find(f.root, n => n['aria-label'] === '打开会话记录')
    mobile.onClick()
    find(f.root, n => n['data-delete'] === 'c1').onClick(); await flush()
    hook.canDelete.value = false; await flush()
    find(f.root, n => n.id === 'delete-session-confirm').onClick()
    assert.deepEqual(calls, [])
    hook.canDelete.value = true; await flush()
    const confirm = find(f.root, n => n.id === 'delete-session-confirm')
    confirm.onClick(); confirm.onClick(); await flush()
    assert.deepEqual(calls, ['c1'])
    assert.equal(dialog.open, false)
    assert.equal(global.document.activeElement, document.trigger)
  } finally { f.app.unmount(); document.restore() }
})

function reviewFixture() {
  const document = documentFixture(), requests = []
  const Upload = vue.defineComponent({ emits: ['submit'], setup: (_, { emit }) => () => vue.h('button', { id: 'submit-review', onClick: () => emit('submit', { mode: 'knowledge_base', file: { name: 'draft.docx' } }) }, '审核') })
  const Report = vue.defineComponent({ props: ['markdown'], emits: ['restart'], setup: (props, { emit }) => () => vue.h('div', [vue.h('pre', props.markdown), vue.h('button', { id: 'restart-review', onClick: () => emit('restart') }, '重来')]) })
  const f = mount('../../views/AgentWorkbenchView.vue', {
    'vue-router': { useRoute: () => ({ params: { agentId: 'institution-review' } }) },
    '../api/client': { ApiError: Error },
    '../api/reviews': { submitReview: (_, signal) => new Promise(resolve => requests.push({ signal, resolve })) },
    '../components/workbench/ExecutionStatus.vue': component(Empty),
    '../features/institution-review/ReviewUpload.vue': component(Upload),
    '../features/institution-review/ReviewReport.vue': component(Report),
  })
  return { ...f, requests, dispose() { f.app.unmount(); document.restore() } }
}
function askStop(f) { find(f.root, n => n.tag === 'button' && text(n) === '停止等待').onClick() }

test('cancelling stop keeps the review request; confirming aborts only client waiting and ignores a late report', async () => {
  const f = reviewFixture()
  try {
    find(f.root, n => n.id === 'submit-review').onClick(); await flush()
    askStop(f); await flush()
    find(f.root, n => n.id === 'stop-review-cancel').onClick(); await flush()
    assert.equal(f.requests[0].signal.aborted, false)
    askStop(f); await flush()
    find(f.root, n => n.id === 'stop-review-confirm').onClick(); await flush()
    assert.equal(f.requests[0].signal.aborted, true)
    f.requests[0].resolve('late report'); await flush()
    assert.doesNotMatch(text(f.root), /late report/)
    assert.match(text(f.root), /已停止等待/)
  } finally { f.dispose() }
})

test('review completion closes a stale stop prompt so it cannot abort the next request', async () => {
  const f = reviewFixture()
  try {
    find(f.root, n => n.id === 'submit-review').onClick(); await flush()
    askStop(f); await flush()
    const stale = find(f.root, n => n.id === 'stop-review-confirm')
    f.requests[0].resolve('completed report'); await flush()
    assert.equal(find(f.root, n => n.tag === 'dialog').open, false)
    find(f.root, n => n.id === 'restart-review').onClick(); await flush()
    find(f.root, n => n.id === 'submit-review').onClick(); await flush()
    stale.onClick()
    assert.equal(f.requests[1].signal.aborted, false)
  } finally { f.dispose() }
})
