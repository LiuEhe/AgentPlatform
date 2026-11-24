// @vitest-environment jsdom
import assert from 'node:assert/strict'
import { flushPromises, mount } from '@vue/test-utils'
import { afterAll, beforeAll, test } from 'vitest'
import { defineComponent, h, markRaw, reactive } from 'vue'
import ConfirmDialog from '../../src/components/ConfirmDialog.vue'

// jsdom does not implement opening and closing modal dialogs.
const dialogMethods = {
  showModal() { this.open = true },
  close() {
    if (!this.open) return
    this.open = false
    queueMicrotask(() => this.dispatchEvent(new Event('close')))
  },
}
const originalMethods = new Map()

beforeAll(() => {
  for (const [name, value] of Object.entries(dialogMethods)) {
    originalMethods.set(name, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name))
    Object.defineProperty(HTMLDialogElement.prototype, name, { configurable: true, value })
  }
})

afterAll(() => {
  for (const [name, descriptor] of originalMethods) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor)
    else delete HTMLDialogElement.prototype[name]
  }
})

function setup(extra = {}) {
  const host = document.createElement('div')
  const trigger = document.createElement('button')
  document.body.append(trigger, host)
  trigger.focus()
  const calls = []
  const props = reactive({
    open: false, title: '确认操作？', confirmLabel: '确认',
    'onUpdate:open': value => { props.open = value },
    onConfirm: () => calls.push('confirmed'), ...extra,
  })
  const wrapper = mount(defineComponent({ setup: () => () => h(ConfirmDialog, { ...props }) }), {
    attachTo: host,
  })
  let mounted = true
  function unmount() {
    if (mounted) wrapper.unmount()
    mounted = false
  }
  return {
    wrapper, props, calls, trigger, unmount,
    action: name => wrapper.get(`[id$="-${name}"]`).element,
    dialog: () => wrapper.get('dialog').element,
    dispose() { unmount(); host.remove(); trigger.remove() },
  }
}

function pressEscape(dialog) {
  dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
}

test('confirmation focuses cancel, closes on Esc or X, and restores the trigger without confirming', async () => {
  const f = setup()
  try {
    f.props.open = true
    await flushPromises()
    assert.equal(f.dialog().open, true)
    assert.equal(document.activeElement, f.action('cancel'))
    pressEscape(f.dialog())
    await flushPromises()
    assert.equal(f.dialog().open, false)
    assert.equal(document.activeElement, f.trigger)
    assert.deepEqual(f.calls, [])
    f.props.open = true
    await flushPromises()
    f.action('close').click()
    await flushPromises()
    assert.equal(f.dialog().open, false)
    assert.deepEqual(f.calls, [])
  } finally { f.dispose() }
})

test('confirmation blocks busy cancellation and duplicate submits, then permits a new opening', async () => {
  const f = setup({ busy: true })
  try {
    f.props.open = true
    await flushPromises()
    pressEscape(f.dialog())
    f.action('confirm').click()
    assert.equal(f.props.open, true)
    assert.deepEqual(f.calls, [])
    f.props.busy = false
    await flushPromises()
    f.action('confirm').click()
    f.action('confirm').click()
    assert.deepEqual(f.calls, ['confirmed'])
    f.props.open = false
    await flushPromises()
    f.props.open = true
    await flushPromises()
    f.props.confirmDisabled = true
    await flushPromises()
    f.action('confirm').click()
    assert.equal(f.calls.length, 1)
    f.props.confirmDisabled = false
    await flushPromises()
    f.action('confirm').click()
    assert.equal(f.calls.length, 2)
  } finally { f.dispose() }
})

test('dialog labels reference the title and focus returns to the replacement for a disappeared control', async () => {
  const f = setup()
  const replacement = markRaw(document.createElement('button'))
  const current = document.createElement('button')
  try {
    document.body.append(replacement, current)
    f.props.returnFocus = replacement
    f.props.open = true
    await flushPromises()
    f.trigger.remove()
    f.action('cancel').click()
    await flushPromises()
    assert.equal(document.activeElement, replacement)
    assert.match(f.wrapper.text(), /确认操作？/)
    const label = document.getElementById(f.dialog().getAttribute('aria-labelledby'))
    assert.equal(label.tagName, 'H2')
    current.focus()
    f.unmount()
    assert.equal(document.activeElement, current, 'An already closed dialog must not steal focus on unmount')
  } finally { f.dispose(); replacement.remove(); current.remove() }
})
