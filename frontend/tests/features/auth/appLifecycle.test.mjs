// @vitest-environment jsdom
import assert from 'node:assert/strict'
import { test, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import * as vue from 'vue'
import App from '../../../src/App.vue'

const dependencies = vi.hoisted(() => ({ route: undefined, auth: undefined }))
vi.mock('vue-router', async original => ({ ...await original(), useRoute: () => dependencies.route }))
vi.mock('../../../src/features/auth/useAuth', async original => ({ ...await original(), useAuth: () => dependencies.auth }))

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
  dependencies.route = route
  dependencies.auth = auth
  const app = mount(App, { global: { stubs: { RouterView, RouterLink, PlatformBrand: Public, AccountMenu: Public } } })
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
