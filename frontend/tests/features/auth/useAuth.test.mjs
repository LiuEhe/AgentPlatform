import assert from 'node:assert/strict'
import { test } from 'vitest'
import { createAuthController } from '../../../src/features/auth/useAuth'

const view = (id='a', sid='one') => ({user:{user_id:id,username:id,must_change_password:false},auth_session_id:sid,csrf_token:'secret',expires_at:new Date(Date.now()+10000).toISOString()})
test('first verified bootstrap preserves only that users scoped refresh pointers', async () => {
  const previous = global.sessionStorage
  const storage = { 'agent-platform-session:a': 'owned-session',
    'agent-platform-session-deletions:a': 'owned-retry',
    'agent-platform-session:b': 'foreign-session', 'agent-platform-session': 'legacy', unrelated: 'keep' }
  Object.defineProperty(storage, 'removeItem', {value:key=>{delete storage[key]}})
  global.sessionStorage = storage
  const auth = createAuthController({me:async()=>view(),logout:async()=>{}})
  try {
    await auth.bootstrap()
    assert.equal(storage['agent-platform-session:a'], 'owned-session')
    assert.equal(storage['agent-platform-session-deletions:a'], 'owned-retry')
    assert.equal(storage['agent-platform-session:b'], undefined)
    assert.equal(storage['agent-platform-session'], undefined)
    await auth.logout()
    assert.equal(storage['agent-platform-session:a'], undefined)
    assert.equal(storage['agent-platform-session-deletions:a'], undefined)
    assert.equal(storage.unrelated, 'keep')
  } finally { auth.dispose(); global.sessionStorage = previous }
})
test('logout clears synchronously and late me cannot restore the old account', async () => {
  let resolve
  let checking = false
  let revoked = 0
  const auth = createAuthController({me: () => checking ? new Promise(r => {resolve=r}) : Promise.resolve(view()),logout:async()=>{revoked++}})
  await auth.bootstrap()
  const old = auth.capture()
  let cleaned = 0
  auth.registerCleanup(() => cleaned++)
  checking=true
  const pending=auth.revalidate()
  await auth.logout()
  assert.equal(cleaned,1)
  assert.equal(revoked,1)
  resolve(view())
  await pending
  assert.equal(auth.phase.value,'anonymous')
  assert.equal(auth.isCurrent(old),false)
  auth.dispose()
})
test('registration does not establish or replace a login; revalidation detects cookie replacement', async () => {
  let current=view()
  const api={me:async()=>current,register:async()=>view('b').user}
  const auth=createAuthController(api)
  await auth.bootstrap()
  await api.register({})
  assert.equal(auth.user.value.user_id,'a')
  let cleaned=0
  auth.registerCleanup(()=>cleaned++)
  current=view('b','two')
  await auth.revalidate()
  assert.equal(cleaned,1)
  assert.equal(auth.user.value.user_id,'b')
  auth.dispose()
})
test('failed logout remains locked and retry never revokes a replacement session', async () => {
  let current=view(), calls=0
  const auth=createAuthController({me:async()=>current,logout:async()=>{calls++;throw new Error('offline')}})
  await auth.bootstrap()
  await auth.logout()
  assert.equal(auth.phase.value,'logout-pending')
  current=view('b','two')
  await auth.logout()
  assert.equal(calls,1)
  assert.equal(auth.user.value,null)
  auth.dispose()
})

test('late logout success cannot overwrite a replacement login confirmed in another tab', async () => {
  const previous = { window:global.window, document:global.document, localStorage:global.localStorage }
  const handlers = new Map(), values = new Map()
  global.window = { addEventListener:(name,fn)=>handlers.set(name,fn), removeEventListener:()=>{} }
  global.document = { hidden:false, addEventListener:()=>{}, removeEventListener:()=>{}, documentElement:{classList:{add:()=>{},remove:()=>{}}} }
  global.localStorage = { getItem:key=>values.get(key)??null, setItem:(key,value)=>values.set(key,value), removeItem:key=>values.delete(key) }
  let current=view(), finishLogout
  const auth=createAuthController({me:async()=>current,logout:()=>new Promise(resolve=>{finishLogout=resolve})})
  try {
    await auth.bootstrap()
    const oldLogout=auth.logout()
    current=view('b','two')
    values.delete('agent-platform-logout-lock')
    handlers.get('storage')({key:'agent-platform-identity-signal'})
    await Promise.resolve(); await Promise.resolve()
    assert.equal(auth.user.value.user_id,'b')
    finishLogout(); await oldLogout
    assert.equal(auth.phase.value,'authenticated')
    assert.equal(auth.capture().userId,'b')
  } finally { auth.dispose(); Object.assign(global,previous) }
})
