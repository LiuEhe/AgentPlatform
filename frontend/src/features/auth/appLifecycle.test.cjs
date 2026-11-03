const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
const vue = require('vue')
const { parse, compileScript } = require('vue/compiler-sfc')

test('same login keeps assistant drafts across public navigation; new epoch destroys them', async () => {
  const route = vue.reactive({ name: 'agent-conversation', meta: { private: true } })
  const auth = { user: vue.ref({ user_id: 'a' }), phase: vue.ref('authenticated'), epoch: vue.ref(1), storageAvailable: vue.ref(true) }
  const drafts = []
  let destroyed = 0
  const Conversation = vue.defineComponent({ name: 'AgentConversationView', setup() {
    const draft = vue.ref('')
    drafts.push(draft)
    vue.onUnmounted(() => destroyed++)
    return () => vue.h('textarea', { value: draft.value })
  } })
  const Public = vue.defineComponent({ setup: () => () => vue.h('div', 'public') })
  const current = vue.shallowRef(Conversation)
  const RouterView = vue.defineComponent({ setup: (_, { slots }) => () => slots.default({ Component: current.value }) })
  const RouterLink = vue.defineComponent({ setup: (_, { slots }) => () => vue.h('a', slots.default?.()) })
  const filename = path.resolve(__dirname, '../../App.vue')
  const compiled = compileScript(parse(fs.readFileSync(filename, 'utf8')).descriptor, { id: 'auth-lifecycle', inlineTemplate: true }).content
  const loaded = new Module(filename, module)
  loaded.paths = module.paths
  loaded.require = id => {
    if (id === 'vue') return vue
    if (id === 'vue-router') return { RouterLink, RouterView, useRoute: () => route }
    if (id === './features/auth/useAuth') return { useAuth: () => auth }
    if (id.endsWith('.vue')) return { __esModule: true, default: Public }
    if (id === '@lucide/vue') return { ArrowLeft: Public, ArrowUpRight: Public }
    throw new Error(`Unexpected import: ${id}`)
  }
  loaded._compile(ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename)
  const element = tag => ({ tag, style: {}, children: [], parent: null })
  const renderer = vue.createRenderer({
    createElement: element, createText: text => ({ text }), createComment: text => ({ text }),
    setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
    patchProp: (node, key, previous, next) => { node[key] = next },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index < 0) parent.children.push(node); else parent.children.splice(index, 0, node)
      node.parent = parent
    },
    remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
  })
  const app = renderer.createApp(loaded.exports.default)
  app.mount(element('root'))
  try {
    drafts[0].value = 'private unsent draft'
    route.name = 'agent-plaza'; route.meta.private = false; current.value = Public
    await vue.nextTick()
    assert.equal(destroyed, 0, 'ordinary navigation must deactivate, not destroy, the cache')
    route.name = 'agent-conversation'; route.meta.private = true; current.value = Conversation
    await vue.nextTick()
    assert.equal(drafts.length, 1)
    assert.equal(drafts[0].value, 'private unsent draft')
    auth.epoch.value++; auth.user.value = { user_id: 'b' }
    await vue.nextTick()
    assert.equal(destroyed, 1)
    assert.equal(drafts.length, 2)
    assert.equal(drafts[1].value, '')
  } finally { app.unmount() }
})
