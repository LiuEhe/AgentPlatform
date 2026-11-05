const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
function load() {
  const calls = []
  const filename = path.join(__dirname, 'users.ts')
  const m = new Module(filename, module)
  m.paths = module.paths
  m.require = id => {
    if (id === './client') return { apiRequest: async (...args) => { calls.push(args); return {} } }
    throw new Error(`Unexpected import: ${id}`)
  }
  m._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, filename)
  return { ...m.exports, calls }
}
test('profile patch preserves omitted and explicitly cleared fields', async () => {
  const f = load()
  await f.getProfile()
  assert.equal(f.calls[0][0], '/api/v1/users/me')
  await f.updateProfile({ bio: 'hello', email: null })
  assert.deepEqual(JSON.parse(f.calls[1][1].body), { bio: 'hello', email: null })
  await f.getUserProfile('a/b')
  assert.equal(f.calls[2][0], '/api/v1/admin/users/a%2Fb')
})
test('avatar uses multipart, bound blob API and empty delete response', async () => {
  const f = load(), signal = new AbortController().signal
  await f.uploadAvatar(new File(['image'], 'a.png', { type: 'image/png' }), signal)
  assert.ok(f.calls[0][1].body instanceof FormData)
  assert.equal(f.calls[0][1].headers, undefined)
  assert.equal(f.calls[0][1].signal, signal)
  await f.getAvatar('a/b', signal)
  assert.equal(f.calls[1][0], '/api/v1/admin/users/a%2Fb/avatar')
  assert.equal(f.calls[1][2], 'blob')
  await f.removeAvatar(signal)
  assert.equal(f.calls[2][1].method, 'DELETE')
  assert.equal(f.calls[2][2], 'empty')
})
