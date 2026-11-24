import * as vue from 'vue'

// The controlled host lets these tests drive dialog, focus and Canvas events directly.
let imports = {}

export function mocked(module, name) {
  return (...args) => imports[module][name](...args)
}
export function stubComponent(module) {
  return vue.defineComponent({
    inheritAttrs: false,
    setup: (_, { attrs, slots }) => () => vue.h(imports[module].default, attrs, slots),
  })
}
export const routerStubs = {
  RouterLink: vue.defineComponent({ setup: (_, { slots }) => () => vue.h('a', slots.default?.()) }),
  onBeforeRouteLeave: (...args) => imports['vue-router']?.onBeforeRouteLeave?.(...args),
  useRouter: () => imports['vue-router']?.useRouter?.(),
  useRoute: () => imports['vue-router']?.useRoute?.(),
}

function mount(component, overrides, props = {}, configureElement = () => ({})) {
  imports = overrides
  function element(tag) {
    return vue.markRaw({ tag, tagName: tag.toUpperCase(), style: {}, children: [], parent: null, listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn },
      removeEventListener(type) { delete this.listeners[type] },
      get options() { return this.children.filter(c => c.tag === 'option') },
      get isConnected() { let node = this; while (node.parent) node = node.parent; return node.tag === 'root' },
      focus() { if (global.document) global.document.activeElement = this },
      getAttribute(name) { return this[name] == null ? null : String(this[name]) },
      contains(target) { for (let node = target; node; node = node.parent) if (node === this) return true; return false },
      scrollIntoView() {},
      showModal() { this.open = true },
      close() { if (!this.open) return; this.open = false; queueMicrotask(() => this.onClose?.({ target: this })) },
      ...configureElement(tag),
    })
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
  const root = element('root'), app = renderer.createApp({ setup: () => () => vue.h(component, { ...props }) })
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
export { mount, find, text, flush, auth, vue }
