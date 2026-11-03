const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
function load() {
  const filename=path.join(__dirname,'client.ts')
  const m=new Module(filename,module)
  m.paths=module.paths
  const source=fs.readFileSync(filename,'utf8').replace('import.meta.env.VITE_API_BASE_URL', "''")
  m._compile(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename)
  let current=true, handled=0
  const ticket={epoch:1,userId:'a',authSessionId:'public-session-id',csrfToken:'memory-only'}
  m.exports.installAuthHooks({capture:()=>ticket,isCurrent:()=>current,onAuthError:()=>handled++})
  return {...m.exports,ticket,replace:()=>{current=false},handled:()=>handled}
}
test('bound JSON/text/blob/204 use credentials and context; only writes carry CSRF',async()=>{
  const f=load(), previous=global.fetch, calls=[]
  global.fetch=async(url,init)=>{calls.push({url,...init});return new Response(init.method==='DELETE'?null:'ok',{status:init.method==='DELETE'?204:200})}
  try {
    assert.equal(await f.apiRequest('/x',{method:'POST'},'text'),'ok')
    assert.equal(calls[0].credentials,'include')
    assert.equal(calls[0].headers.get('X-Auth-Session-ID'),'public-session-id')
    assert.equal(calls[0].headers.get('X-CSRF-Token'),'memory-only')
    await f.apiRequest('/x',{},'blob')
    assert.equal(calls[1].headers.has('X-CSRF-Token'),false)
    assert.equal(await f.apiRequest('/x',{method:'DELETE'},'empty'),undefined)
  } finally {global.fetch=previous}
})
test('late response cannot return private content or invalidate a newer login',async()=>{
  const f=load(),previous=global.fetch
  let release
  global.fetch=()=>new Promise(r=>{release=r})
  try {
    const pending=f.apiRequest('/private',{},'blob')
    f.replace()
    release(new Response('old report'))
    await assert.rejects(pending,error=>error.name==='AbortError')
    assert.equal(f.handled(),0)
  } finally {global.fetch=previous}
})
test('public login errors stay at the form; bound auth errors use the current-ticket hook',async()=>{
  const f=load(),previous=global.fetch
  global.fetch=async()=>new Response(JSON.stringify({error:{code:'AUTH_REQUIRED',message:'expired'}}),{status:401})
  try {
    await assert.rejects(f.apiRequest('/login',{method:'POST'},'json','public-auth'))
    assert.equal(f.handled(),0)
    await assert.rejects(f.apiRequest('/private'))
    assert.equal(f.handled(),1)
  } finally {global.fetch=previous}
})
