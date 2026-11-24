import assert from 'node:assert/strict'
import { test, vi } from 'vitest'
import * as users from '../../src/api/users'
import { apiRequest } from '../../src/api/client'

vi.mock('../../src/api/client', () => ({ apiRequest: vi.fn(async () => ({})) }))

function fixture() {
  apiRequest.mockClear()
  return { ...users, calls: apiRequest.mock.calls }
}

test('profile patch preserves omitted and explicitly cleared fields', async () => {
  const f = fixture()
  await f.getProfile()
  assert.equal(f.calls[0][0], '/api/v1/users/me')
  await f.updateProfile({ bio: 'hello', email: null })
  assert.deepEqual(JSON.parse(f.calls[1][1].body), { bio: 'hello', email: null })
  await f.getUserProfile('a/b')
  assert.equal(f.calls[2][0], '/api/v1/admin/users/a%2Fb')
})
test('avatar uses multipart, bound blob API and empty delete response', async () => {
  const f = fixture(), signal = new AbortController().signal
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
