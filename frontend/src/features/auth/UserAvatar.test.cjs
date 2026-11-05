const test = require('node:test')
const assert = require('node:assert/strict')
const { mount, find, flush, auth, vue } = require('./componentTestHarness.cjs')
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript')
function realAuth(api) {
  const filename = path.join(__dirname, 'useAuth.ts'), m = new Module(filename, module)
  m.paths = module.paths
  m.require = id => id === 'vue' ? vue : { ApiError: class extends Error {} }
  m._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, filename)
  return m.exports.createAuthController(api)
}
test('late avatar does not replace new target and urls are revoked', async () => {
  const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL
  const requests = [], revoked = [], identity = auth()
  URL.createObjectURL = blob => 'blob:' + blob.id
  URL.revokeObjectURL = url => revoked.push(url)
  const props = vue.reactive({ hasAvatar: true, userId: 'a', revision: 1, alt: 'Alice' })
  const f = mount('UserAvatar.vue', { '../../api/users': { getAvatar: id => new Promise(resolve => requests.push({ id, resolve })) },
    './useAuth': { useAuth: () => identity } }, props)
  try {
    await flush()
    props.userId = 'b'
    await flush()
    requests[1].resolve({ id: 'b' })
    await flush()
    requests[0].resolve({ id: 'a' })
    await flush()
    assert.equal(find(f.root, n => n.tag === 'img').src, 'blob:b')
    props.revision++
    await flush()
    requests[2].resolve({ id: 'b-new' })
    await flush()
    assert.equal(find(f.root, n => n.tag === 'img').src, 'blob:b-new')
    assert.ok(revoked.includes('blob:b'))
  } finally {
    f.app.unmount()
    assert.ok(revoked.includes('blob:b-new'))
    URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke
  }
})
test('avatar reloads after real auth checking becomes authenticated with same epoch', async () => {
  let release, reads = 0, calls = 0
  const view = () => ({ user: { user_id: 'a', has_avatar: true }, auth_session_id: 'one', csrf_token: 'csrf', expires_at: new Date(Date.now() + 60000).toISOString() })
  const identity = realAuth({ me: async () => ++reads === 1 ? view() : new Promise(resolve => { release = resolve }) })
  await identity.bootstrap()
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL
  URL.createObjectURL = () => 'blob:avatar'; URL.revokeObjectURL = () => {}
  const props = vue.reactive({ hasAvatar: true, revision: 1, alt: 'Alice' })
  const f = mount('UserAvatar.vue', { '../../api/users': { getAvatar: async () => { calls++; return new Blob(['image']) } }, './useAuth': { useAuth: () => identity } }, props)
  try {
    await flush()
    assert.equal(calls, 1)
    const epoch = identity.epoch.value
    props.revision++
    const pending = identity.revalidate()
    await flush()
    assert.equal(identity.phase.value, 'checking')
    release(view()); await pending; await flush()
    assert.equal(identity.epoch.value, epoch)
    assert.equal(calls, 2)
    assert.equal(find(f.root, n => n.tag === 'img').src, 'blob:avatar')
  } finally { f.app.unmount(); identity.dispose(); URL.createObjectURL = create; URL.revokeObjectURL = revoke }
})
