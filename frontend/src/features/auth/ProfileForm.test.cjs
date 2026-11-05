const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, text, flush, auth, vue } = require('./componentTestHarness.cjs')
const profile = { user_id: 'a', username: 'alice', display_name: 'Alice', role: 'user', has_avatar: false, updated_at: 'one',
  email: 'old@example.com', gender: null, birthday: null, phone_number: null, address: null, bio: 'old' }
function setup(api) {
  const identity = auth()
  const previous = global.document
  global.document = { activeElement: null }
  const f = mount('ProfileForm.vue', { '../../api/client': { ApiError: class extends Error {} }, '../../api/users': { getProfile: async () => ({ ...profile }), ...api },
    './useAuth': { useAuth: () => identity }, './UserAvatar.vue': { __esModule: true, default: vue.defineComponent({ setup: () => () => vue.h('span') }) },
    './AvatarCropper.vue': { __esModule: true, default: vue.defineComponent({ props: ['file'], emits: ['confirm', 'cancel'], setup: (_, { emit }) => () => vue.h('div', [
      vue.h('button', { id: 'test-confirm-crop', onClick: () => emit('confirm', new File(['cropped'], 'avatar.png', { type: 'image/png' })) }, 'Confirm crop'),
      vue.h('button', { id: 'test-cancel-crop', onClick: () => emit('cancel') }, 'Cancel crop'),
    ]) }) },
  })
  return { ...f, identity, dispose() { f.app.unmount(); global.document = previous } }
}
function edit(f, id, value) {
  const input = find(f.root, n => n.id === id)
  assert.ok(input, `Missing ${id}`)
  input.value = value
  input.listeners.input({ target: input })
}
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
    assert.equal(input.max, '2026-11-04')
    Date.now = () => Date.parse('2026-11-04T16:00:00Z')
    input.onFocus()
    await flush()
    assert.equal(input.max, '2026-11-05')
  } finally { f.dispose(); Date.now = now }
})
