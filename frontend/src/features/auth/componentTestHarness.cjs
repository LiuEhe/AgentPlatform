const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const ts = require('typescript')
const vue = require('vue')
const { parse, compileScript } = require('vue/compiler-sfc')
function mount(name, imports, props = {}, configureElement = () => ({})) {
  const filename = path.join(__dirname, name)
  const source = compileScript(parse(fs.readFileSync(filename, 'utf8')).descriptor, {
    id: name, inlineTemplate: true,
  }).content
  const m = new Module(filename, module)
  m.paths = module.paths
  m.require = id => {
    if (id === 'vue') return vue
    if (id === 'vue-router') return { RouterLink: vue.defineComponent({ setup: (_, { slots }) => () => vue.h('a', slots.default?.()) }), onBeforeRouteLeave() {}, ...imports[id] }
    if (id === '@lucide/vue') return require('@lucide/vue')
    if (id in imports) return imports[id]
    throw new Error(`Unexpected import ${id}`)
  }
  m._compile(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, filename)
  function element(tag) {
    return { tag, tagName: tag.toUpperCase(), style: {}, children: [], parent: null, listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn },
      removeEventListener(type) { delete this.listeners[type] },
      get options() { return this.children.filter(c => c.tag === 'option') },
      showModal() { this.open = true }, close() { this.open = false }, ...configureElement(tag),
    }
  }
  const renderer = vue.createRenderer({
    createElement: element, createText: text => ({ text }), createComment: text => ({ text }),
    insertStaticContent(content, parent, anchor) {
      const node = element('static'); node.text = content; node.parent = parent
      const at = anchor ? parent.children.indexOf(anchor) : -1
      at < 0 ? parent.children.push(node) : parent.children.splice(at, 0, node)
      return [node, node]
    },
    setText(node, text) { node.text = text },
    setElementText(node, text) { node.text = text; node.children = [] },
    patchProp(node, key, prev, next) { node[key] = next },
    parentNode: node => node?.parent,
    nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      const at = anchor ? parent.children.indexOf(anchor) : -1
      at < 0 ? parent.children.push(node) : parent.children.splice(at, 0, node)
      node.parent = parent
    },
    remove(node) {
      if (node.parent) { const at = node.parent.children.indexOf(node); if (at >= 0) node.parent.children.splice(at, 1) }
      node.parent = null
    },
  })
  const root = element('root'), app = renderer.createApp({ setup: () => () => vue.h(m.exports.default, { ...props }) })
  app.mount(root)
  return { root, app }
}
function find(root, predicate) {
  if (predicate(root)) return root
  for (const child of root.children ?? []) { const found = find(child, predicate); if (found) return found }
}
function text(root) { return (root.text ?? '') + (root.children ?? []).map(text).join('') }
async function flush() { await vue.nextTick(); await new Promise(setImmediate); await vue.nextTick() }
function auth() {
  const epoch = vue.ref(1)
  return { epoch, phase: vue.ref('authenticated'), user: vue.ref({ user_id: 'a', username: 'alice', display_name: 'Alice', role: 'user', has_avatar: false, updated_at: 'one' }),
    capture: () => ({ epoch: epoch.value }), isCurrent: ticket => ticket.epoch === epoch.value,
    revalidate: async () => {},
  }
}
module.exports = { mount, find, text, flush, auth, vue }
