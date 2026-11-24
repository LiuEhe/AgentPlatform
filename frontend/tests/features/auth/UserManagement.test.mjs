// @vitest-environment jsdom
import assert from 'node:assert/strict'
import { test, vi } from 'vitest'
import { mount, find, text, flush, auth, vue, mocked, stubComponent } from '../../helpers/componentTestHarness.mjs'
import UserManagement from '../../../src/features/auth/UserManagement.vue'

vi.mock('../../../src/features/auth/useAuth', async original => ({ ...await original(), useAuth: mocked('./useAuth', 'useAuth') }))
vi.mock('../../../src/features/auth/UserAvatar.vue', () => ({ default: stubComponent('./UserAvatar.vue') }))
vi.mock('../../../src/api/users', async original => ({ ...await original(), createUser: mocked('../../api/users', 'createUser'), getUserProfile: mocked('../../api/users', 'getUserProfile'), listUsers: mocked('../../api/users', 'listUsers'), resetUserPassword: mocked('../../api/users', 'resetUserPassword'), setUserStatus: mocked('../../api/users', 'setUserStatus') }))

const users = [{ user_id: 'a', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active' },
  { user_id: 'b', username: 'bob', display_name: 'Bob', role: 'user', status: 'disabled' }]
function setup(getUserProfile, api = {}) {
  const identity = auth(), previous = global.document
  global.document = { activeElement: null }
  const f = mount(UserManagement, { '../../api/users': { listUsers: async () => ({ items: users, next_cursor: null }), getUserProfile, ...api },
    './useAuth': { useAuth: () => identity }, './UserAvatar.vue': { __esModule: true, default: vue.defineComponent({ setup: () => () => vue.h('span') }) } })
  return { ...f, identity, dispose() { f.app.unmount(); global.document = previous } }
}
test('admin can view builtin and disabled users in read-only details', async () => {
  const f = setup(async id => ({ ...users.find(u => u.user_id === id), email: 'visible@example.com', bio: '<b>plain text</b>', has_avatar: false, updated_at: 'one' }))
  try {
    await flush()
    for (const user of users) {
      const button = find(f.root, n => n['data-profile-user'] === user.user_id)
      assert.ok(button, 'view action available for each user')
      await button.onClick()
      await flush()
      const detail = find(f.root, n => n.id === 'profile-dialog')
      assert.equal(detail.open, true)
      assert.match(text(detail), /visible@example.com/)
      assert.match(text(detail), /未填写/)
      assert.equal(find(detail, n => n.tag === 'input' || n.tag === 'textarea'), undefined)
    }
  } finally { f.dispose() }
})

test('account status asks before requesting, cancellation preserves status and confirmation uses the opened target', async () => {
  const calls = []
  const f = setup(async () => ({}), { setUserStatus: async (...args) => calls.push(args) })
  try {
    await flush()
    find(f.root, n => n.tag === 'button' && text(n) === '启用').onClick(); await flush()
    assert.deepEqual(calls, [])
    find(f.root, n => n.id === 'user-status-cancel').onClick(); await flush()
    assert.deepEqual(calls, [])
    find(f.root, n => n.tag === 'button' && text(n) === '启用').onClick(); await flush()
    const confirm = find(f.root, n => n.id === 'user-status-confirm')
    confirm.onClick(); confirm.onClick(); await flush()
    assert.deepEqual(calls, [['b', 'active']])
  } finally { f.dispose() }
})

test('identity changes invalidate an open account status confirmation', async () => {
  const calls = []
  const f = setup(async () => ({}), { setUserStatus: async (...args) => calls.push(args) })
  try {
    await flush()
    find(f.root, n => n.tag === 'button' && text(n) === '启用').onClick(); await flush()
    const confirm = find(f.root, n => n.id === 'user-status-confirm')
    f.identity.epoch.value++
    confirm.onClick(); await flush()
    assert.deepEqual(calls, [])
    assert.equal(find(f.root, n => n.tag === 'dialog' && n['aria-labelledby'] === 'user-status-title').open, false)
  } finally { f.dispose() }
})
test('old target detail response cannot overwrite current target', async () => {
  const requests = [], f = setup(id => new Promise(resolve => requests.push({ id, resolve })))
  try {
    await flush()
    find(f.root, n => n['data-profile-user'] === 'a').onClick()
    find(f.root, n => n['data-profile-user'] === 'b').onClick()
    requests[1].resolve({ ...users[1], email: 'bob@example.com' })
    await flush()
    requests[0].resolve({ ...users[0], email: 'old@example.com' })
    await flush()
    const detail = find(f.root, n => n.id === 'profile-dialog')
    assert.match(text(detail), /bob@example.com/)
    assert.doesNotMatch(text(detail), /old@example.com/)
  } finally { f.dispose() }
})
