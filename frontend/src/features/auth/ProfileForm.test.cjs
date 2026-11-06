const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, text, flush, auth, vue } = require('./componentTestHarness.cjs')
const profile = { user_id: 'a', username: 'alice', display_name: 'Alice', role: 'user', has_avatar: false, updated_at: 'one',
  email: 'old@example.com', gender: null, birthday: null, phone_number: null, address: null, bio: 'old' }
function setup(api) {
  const identity = auth()
  let leaveGuard
  const previous = global.document
  global.document = { activeElement: null, addEventListener() {}, removeEventListener() {} }
  const f = mount('ProfileForm.vue', { '../../api/client': { ApiError: class extends Error {} }, '../../api/users': { getProfile: async () => ({ ...profile }), ...api },
    'vue-router': { onBeforeRouteLeave: guard => { leaveGuard = guard } },
    './useAuth': { useAuth: () => identity }, './UserAvatar.vue': { __esModule: true, default: vue.defineComponent({ setup: () => () => vue.h('span') }) },
    './AvatarCropper.vue': { __esModule: true, default: vue.defineComponent({ props: ['file'], emits: ['confirm', 'cancel'], setup: (_, { emit }) => () => vue.h('div', [
      vue.h('button', { id: 'test-confirm-crop', onClick: () => emit('confirm', new File(['cropped'], 'avatar.png', { type: 'image/png' })) }, 'Confirm crop'),
      vue.h('button', { id: 'test-cancel-crop', onClick: () => emit('cancel') }, 'Cancel crop'),
    ]) }) },
  })
  return { ...f, identity, leave: () => leaveGuard(), dispose() { f.app.unmount(); global.document = previous } }
}
function edit(f, id, value) {
  const input = find(f.root, n => n.id === id)
  assert.ok(input, `Missing ${id}`)
  input.value = value
  ;(input.listeners.input ?? input.onInput)({ target: input })
}
test('unsaved profile navigation waits for shared confirmation; cancel keeps draft and confirm leaves', async () => {
  const previous = global.window
  global.window = { confirm: () => { throw Error('native confirmation must not be used') } }
  const f = setup({})
  try {
    await flush()
    assert.equal(f.leave(), true)
    edit(f, 'profile-bio', 'keep unsaved signature'); await flush()
    const cancelled = f.leave()
    assert.ok(cancelled instanceof Promise)
    await flush()
    find(f.root, n => n.id === 'profile-leave-cancel').onClick()
    await flush()
    assert.equal(await cancelled, false)
    assert.equal(find(f.root, n => n.id === 'profile-bio').value, 'keep unsaved signature')
    const confirmed = f.leave(); await flush()
    find(f.root, n => n.id === 'profile-leave-confirm').onClick()
    assert.equal(await confirmed, true)
  } finally { f.dispose(); global.window = previous }
})
test('identity change and unmount settle pending profile navigation without allowing stale confirmation', async () => {
  const f = setup({})
  try {
    await flush(); edit(f, 'profile-bio', 'draft'); await flush()
    const pending = f.leave(); await flush()
    const confirm = find(f.root, n => n.id === 'profile-leave-confirm').onClick
    f.identity.epoch.value++; await flush()
    assert.equal(await pending, false)
    confirm(); await flush()
    const next = f.leave(); await flush()
    f.app.unmount()
    assert.equal(await next, false)
  } finally { f.dispose() }
})
test('manual birthday rejects impossible dates and saves leap dates or clearing as ISO/null', async () => {
  const calls = [], f = setup({ updateProfile: async patch => { calls.push(patch); return { ...profile, ...patch } } })
  try {
    await flush()
    for (const value of ['2001-02-29', '1900-02-29', '2000-13-01', '0000-01-01', '2000-2-1', '9999-01-01']) {
      edit(f, 'profile-birthday', value); await flush()
      await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
      assert.equal(calls.length, 0, `invalid birthday ${value} must not be sent`)
    }
    edit(f, 'profile-birthday', '2000-02-29'); await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
    assert.deepEqual(calls, [{ birthday: '2000-02-29' }])
    edit(f, 'profile-birthday', ''); await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
    assert.deepEqual(calls[1], { birthday: null })
  } finally { f.dispose() }
})
test('gender popup supports keyboard selection, cancellation and clearing without changing API values', async () => {
  const calls = [], f = setup({ updateProfile: async patch => { calls.push(patch); return { ...profile, ...patch } } })
  const key = (node, value) => node.onKeydown({ key: value, preventDefault() {}, stopPropagation() {} })
  try {
    await flush()
    const trigger = find(f.root, n => n.id === 'profile-gender')
    assert.equal(trigger.tag, 'button', 'gender must use a styled keyboard picker')
    trigger.onClick(); await flush()
    let list = find(f.root, n => n.role === 'listbox')
    key(list.parent, 'ArrowDown'); await flush()
    global.document.activeElement.onClick(); await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
    assert.deepEqual(calls, [{ gender: 'male' }])
    trigger.onClick(); await flush()
    list = find(f.root, n => n.role === 'listbox')
    key(list.parent, 'Escape'); await flush()
    assert.equal(find(f.root, n => n.role === 'listbox'), undefined)
    assert.equal(global.document.activeElement, trigger)
    trigger.onClick(); await flush()
    find(f.root, n => n.role === 'option' && text(n).includes('未填写')).onClick(); await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
    assert.deepEqual(calls[1], { gender: null })
  } finally { f.dispose() }
})
test('birthday calendar supports leap-day keyboard movement, quick year/month selection and no future choices', async () => {
  const calls = [], f = setup({ updateProfile: async patch => { calls.push(patch); return { ...profile, ...patch } } })
  try {
    await flush(); edit(f, 'profile-birthday', '2000-02-28'); await flush()
    const trigger = find(f.root, n => n['aria-label'] === '选择生日')
    assert.ok(trigger, 'birthday must offer a styled calendar')
    trigger.onClick(); await flush()
    const day = find(f.root, n => n['data-date'] === '2000-02-28')
    day.onKeydown({ key: 'ArrowRight', preventDefault() {}, shiftKey: false }); await flush()
    assert.equal(global.document.activeElement['data-date'], '2000-02-29')
    global.document.activeElement.onClick(); await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} }); await flush()
    assert.deepEqual(calls, [{ birthday: '2000-02-29' }])
    trigger.onClick(); await flush()
    find(f.root, n => n['aria-label'] === '快速选择年月').onClick(); await flush()
    const year = find(f.root, n => n['data-year'] === 2001)
    year.focus(); year.onClick(); await flush()
    const month = find(f.root, n => n['data-month'] === 4)
    month.focus(); month.onClick(); await flush()
    assert.equal(global.document.activeElement['data-date'], '2001-04-01')
    find(f.root, n => n['data-date'] === '2001-04-07').onClick(); await flush()
    assert.equal(find(f.root, n => n.id === 'profile-birthday').value, '2001-04-07')
    edit(f, 'profile-birthday', ''); await flush()
    trigger.onClick(); await flush()
    const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10)
    const tomorrow = new Date(`${today}T00:00:00Z`); tomorrow.setUTCDate(tomorrow.getUTCDate() + 1)
    const future = find(f.root, n => n['data-date'] === tomorrow.toISOString().slice(0, 10))
    assert.ok(future?.disabled)
  } finally { f.dispose() }
})
test('calendar can move forward from a valid birthday with a year below 1000', async () => {
  const f = setup({})
  try {
    await flush(); edit(f, 'profile-birthday', '0099-06-15'); await flush()
    await find(f.root, n => n['aria-label'] === '选择生日').onClick(); await flush()
    const next = find(f.root, n => n['aria-label'] === '下个月')
    assert.equal(next.disabled, false)
    next.onClick(); await flush()
    assert.ok(find(f.root, n => n['data-date'] === '0099-07-15'))
  } finally { f.dispose() }
})
test('signature save sends only changed field and failed save keeps draft', async () => {
  const calls = [], f = setup({ updateProfile: async input => { calls.push(input); throw Error('controlled failure') } })
  try {
    await flush()
    edit(f, 'profile-bio', 'new signature')
    await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} })
    await flush()
    assert.deepEqual(calls, [{ bio: 'new signature' }])
    assert.equal(find(f.root, n => n.id === 'profile-bio').value, 'new signature')
    assert.match(text(f.root), /controlled failure/)
  } finally { f.dispose() }
})
test('profile response after identity change is ignored', async () => {
  let release
  const f = setup({ getProfile: () => new Promise(resolve => { release = resolve }) })
  try {
    f.identity.epoch.value++
    release(profile)
    await flush()
    assert.equal(find(f.root, n => n.id === 'profile-email'), undefined)
  } finally { f.dispose() }
})
test('avatar success preserves unsaved email and only saves that change later', async () => {
  const uploads = [], calls = [], f = setup({ uploadAvatar: async file => { uploads.push(file); return { ...profile, has_avatar: true, updated_at: 'two' } },
    updateProfile: async input => { calls.push(input); return { ...profile, ...input, has_avatar: true } } })
  try {
    await flush()
    edit(f, 'profile-email', 'new@example.com')
    await flush()
    const fileInput = find(f.root, n => n.tag === 'input' && n.type === 'file')
    fileInput.onChange({ target: { files: [new File(['image'], 'a.png')], value: 'a.png' } })
    await flush()
    assert.equal(uploads.length, 0)
    find(f.root, n => n.id === 'test-confirm-crop').onClick()
    await flush()
    assert.equal(uploads[0].name, 'avatar.png')
    assert.equal(uploads[0].type, 'image/png')
    assert.equal(find(f.root, n => n.id === 'profile-email').value, 'new@example.com')
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} })
    await flush()
    assert.deepEqual(calls, [{ email: 'new@example.com' }])
  } finally { f.dispose() }
})
test('code point limits and clearing optional data are enforced', async () => {
  const calls = [], f = setup({ updateProfile: async input => { calls.push(input); return { ...profile, ...input } } })
  try {
    await flush()
    edit(f, 'profile-bio', '😀'.repeat(200))
    edit(f, 'profile-email', '')
    await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} })
    await flush()
    assert.equal(Array.from(calls[0].bio).length, 200)
    assert.equal(calls[0].email, null)
    edit(f, 'profile-bio', '😀'.repeat(201))
    await flush()
    await find(f.root, n => n.tag === 'form').onSubmit({ preventDefault() {} })
    await flush()
    assert.equal(calls.length, 1)
    assert.match(text(f.root), /最多200个字符/)
  } finally { f.dispose() }
})
test('lost upload response confirms saved avatar without overwriting text draft', async () => {
  let reads = 0
  const f = setup({ getProfile: async () => ++reads === 1 ? { ...profile } : { ...profile, has_avatar: true, updated_at: 'two' },
    uploadAvatar: async () => { throw Error('upload response lost') } })
  try {
    await flush()
    edit(f, 'profile-email', 'unsent@example.com'); await flush()
    find(f.root, n => n.tag === 'input' && n.type === 'file').onChange({ target: { files: [new File(['x'], 'a.png')], value: 'a.png' } })
    await flush()
    find(f.root, n => n.id === 'test-confirm-crop').onClick(); await flush()
    assert.equal(reads, 2)
    assert.equal(find(f.root, n => n.id === 'profile-email').value, 'unsent@example.com')
    assert.equal(find(f.root, n => n.tag === 'button' && n['aria-label'] === '编辑头像').disabled, false)
  } finally { f.dispose() }
})
test('lost upload response offers confirmation retry and preserves signature draft', async () => {
  let reads = 0
  const f = setup({ getProfile: async () => {
    reads++
    if (reads === 1) return { ...profile, has_avatar: true }
    if (reads === 2) throw Error('confirmation unavailable')
    return { ...profile, has_avatar: true }
  }, uploadAvatar: async () => { throw Error('upload response lost') } })
  try {
    await flush()
    edit(f, 'profile-bio', 'unsent signature'); await flush()
    find(f.root, n => n.tag === 'input' && n.type === 'file').onChange({ target: { files: [new File(['x'], 'a.png')], value: 'a.png' } })
    await flush()
    find(f.root, n => n.id === 'test-confirm-crop').onClick()
    await flush()
    assert.equal(reads, 2)
    const retry = find(f.root, n => n.tag === 'button' && text(n) === '重新确认头像状态')
    assert.ok(retry)
    await retry.onClick(); await flush()
    assert.equal(reads, 3)
    assert.equal(find(f.root, n => n.id === 'profile-bio').value, 'unsent signature')
    assert.equal(find(f.root, n => n.tag === 'button' && n['aria-label'] === '编辑头像').disabled, false)
  } finally { f.dispose() }
})

test('cancel crop and reject oversized original without uploading or losing text', async () => {
  let uploads = 0
  const f = setup({ uploadAvatar: async () => { uploads++; return profile } })
  try {
    await flush(); edit(f, 'profile-bio', 'keep this draft'); await flush()
    const choose = file => find(f.root, n => n.type === 'file').onChange({ target: { files: [file], value: file.name } })
    choose(new File(['image'], 'a.png')); await flush()
    find(f.root, n => n.id === 'test-cancel-crop').onClick(); await flush()
    assert.equal(find(f.root, n => n.id === 'test-confirm-crop'), undefined)
    choose(new File([new Uint8Array(2097153)], 'too-big.png', { type: 'image/png' })); await flush()
    assert.equal(find(f.root, n => n.id === 'test-confirm-crop'), undefined)
    assert.match(text(f.root), /2 MB/)
    assert.equal(uploads, 0)
    assert.equal(find(f.root, n => n.id === 'profile-bio').value, 'keep this draft')
  } finally { f.dispose() }
})

test('crop confirmation after identity changed cannot upload for the new identity', async () => {
  let uploads = 0
  const f = setup({ uploadAvatar: async () => { uploads++; return profile } })
  try {
    await flush()
    find(f.root, n => n.type === 'file').onChange({ target: { files: [new File(['x'], 'a.png')], value: 'a.png' } })
    await flush()
    f.identity.epoch.value++
    find(f.root, n => n.id === 'test-confirm-crop').onClick(); await flush()
    assert.equal(uploads, 0)
  } finally { f.dispose() }
})
test('birthday picker refreshes platform date when focused after midnight', async () => {
  const now = Date.now
  Date.now = () => Date.parse('2026-11-04T15:59:59Z')
  const f = setup({})
  try {
    await flush()
    const input = find(f.root, n => n.id === 'profile-birthday')
    const trigger = find(f.root, n => n['aria-label'] === '选择生日')
    await trigger.onClick(); await flush()
    assert.equal(find(f.root, n => n['data-date'] === '2026-11-05').disabled, true)
    const picker = find(f.root, n => n.id === 'profile-birthday-calendar').parent
    picker.onKeydown({ key: 'Escape', preventDefault() {}, stopPropagation() {} }); await flush()
    Date.now = () => Date.parse('2026-11-04T16:00:00Z')
    input.onFocus()
    await flush()
    await trigger.onClick(); await flush()
    assert.equal(find(f.root, n => n['data-date'] === '2026-11-05').disabled, false)
  } finally { f.dispose(); Date.now = now }
})
