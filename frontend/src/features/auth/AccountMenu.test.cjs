const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, flush, auth, vue } = require('./componentTestHarness.cjs')

test('account navigation closes dropdown; cancelled logout preserves login and confirmed logout redirects', async () => {
  const previous = global.document, calls = [], identity = auth()
  global.document = { activeElement: null, addEventListener() {}, removeEventListener() {} }
  identity.logout = async () => calls.push('logout')
  const f = mount('AccountMenu.vue', { './useAuth': { useAuth: () => identity },
    'vue-router': { useRouter: () => ({ replace: async path => calls.push(path) }) },
    './UserAvatar.vue': { __esModule: true, default: vue.defineComponent({ setup: () => () => vue.h('span') }) },
  })
  try {
    await flush()
    const details = find(f.root, n => n.tag === 'details')
    assert.ok(details)
    const summary = find(f.root, n => n.tag === 'summary')
    summary.focus = () => { global.document.activeElement = summary }
    details.querySelector = () => summary
    global.document.activeElement = find(f.root, n => n.id === 'account-logout-trigger')
    details.open = true
    details.onKeydown({ key: 'Escape', preventDefault() {}, stopPropagation() {} })
    assert.ok(global.document.activeElement === summary, 'Esc should return focus to the visible account trigger')
    details.open = true
    find(f.root, n => n.tag === 'a' && n.to === '/account').onClick()
    assert.equal(details.open, false)
    find(f.root, n => n.id === 'account-logout-trigger').onClick(); await flush()
    assert.ok(global.document.activeElement === summary, 'Logout dialog should restore to the visible trigger')
    assert.equal(find(f.root, n => n.tag === 'dialog').open, true)
    find(f.root, n => n.id === 'account-logout-cancel').onClick(); await flush()
    assert.deepEqual(calls, [])
    assert.equal(find(f.root, n => n.tag === 'dialog').open, false)
    find(f.root, n => n.id === 'account-logout-trigger').onClick(); await flush()
    await find(f.root, n => n.id === 'account-logout-confirm').onClick(); await flush()
    assert.deepEqual(calls, ['logout', '/login'])
  } finally { f.app.unmount(); global.document = previous }
})
