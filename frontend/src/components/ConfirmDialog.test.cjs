const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, text, flush, vue } = require('../features/auth/componentTestHarness.cjs')

function setup(extra = {}) {
  const previous = global.document, calls = []
  let mounted = true
  const trigger = { isConnected: true, focus() { global.document.activeElement = this } }
  global.document = { activeElement: trigger }
  const props = vue.reactive({ open: false, title: '确认操作？', confirmLabel: '确认',
    'onUpdate:open': value => { props.open = value }, onConfirm: () => calls.push('confirmed'), ...extra })
  const f = mount('../../components/ConfirmDialog.vue', {}, props)
  return { ...f, props, calls, trigger, unmount() { if (mounted) f.app.unmount(); mounted = false },
    dispose() { if (mounted) f.app.unmount(); global.document = previous } }
}
function action(f, suffix) { return find(f.root, n => n.id?.endsWith('-' + suffix)) }

test('confirmation focuses cancel, closes on Esc or X, and restores the trigger without confirming', async () => {
  const f = setup()
  try {
    f.props.open = true; await flush()
    const dialog = find(f.root, n => n.tag === 'dialog')
    assert.equal(dialog.open, true)
    assert.equal(global.document.activeElement, action(f, 'cancel'))
    dialog.onCancel({ preventDefault() {} }); await flush()
    assert.equal(dialog.open, false)
    assert.equal(global.document.activeElement, f.trigger)
    assert.deepEqual(f.calls, [])
    f.props.open = true; await flush()
    action(f, 'close').onClick(); await flush()
    assert.equal(dialog.open, false)
    assert.deepEqual(f.calls, [])
  } finally { f.dispose() }
})

test('confirmation blocks busy cancellation and duplicate submits, then permits a new opening', async () => {
  const f = setup({ busy: true })
  try {
    f.props.open = true; await flush()
    const dialog = find(f.root, n => n.tag === 'dialog')
    dialog.onCancel({ preventDefault() {} })
    action(f, 'confirm').onClick()
    assert.equal(f.props.open, true)
    assert.deepEqual(f.calls, [])
    f.props.busy = false; await flush()
    action(f, 'confirm').onClick(); action(f, 'confirm').onClick()
    assert.deepEqual(f.calls, ['confirmed'])
    f.props.open = false; await flush()
    f.props.open = true; await flush()
    f.props.confirmDisabled = true; await flush()
    action(f, 'confirm').onClick()
    assert.equal(f.calls.length, 1)
    f.props.confirmDisabled = false; await flush()
    action(f, 'confirm').onClick()
    assert.equal(f.calls.length, 2)
  } finally { f.dispose() }
})

test('dialog labels reference the title and focus returns to the replacement for a disappeared control', async () => {
  const f = setup()
  try {
    const replacement = vue.markRaw({ isConnected: true, focus() { global.document.activeElement = this } })
    f.props.returnFocus = replacement
    f.props.open = true; await flush()
    f.trigger.isConnected = false
    action(f, 'cancel').onClick(); await flush()
    assert.equal(global.document.activeElement, replacement)
    assert.equal(text(f.root).includes('确认操作？'), true)
    const dialog = find(f.root, n => n.tag === 'dialog')
    assert.equal(find(f.root, n => n.id === dialog['aria-labelledby']).tag, 'h2')
    const current = { isConnected: true }
    global.document.activeElement = current
    f.unmount()
    assert.equal(global.document.activeElement, current, 'An already closed dialog must not steal focus on unmount')
  } finally { f.dispose() }
})
