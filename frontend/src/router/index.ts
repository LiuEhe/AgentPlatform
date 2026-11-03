import { createRouter, createWebHistory } from 'vue-router'
import AgentHomeView from '../views/AgentHomeView.vue'
import AgentPlazaView from '../views/AgentPlazaView.vue'
import AgentWorkbenchView from '../views/AgentWorkbenchView.vue'
import AgentFlowView from '../views/AgentFlowView.vue'
import AgentConversationView from '../views/AgentConversationView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import AccountView from '../views/AccountView.vue'
import PasswordView from '../views/PasswordView.vue'
import UserManagementView from '../views/UserManagementView.vue'
import type { AuthController } from '../features/auth/types'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/register', name: 'register', component: RegisterView },
    { path: '/account', name: 'account', component: AccountView, meta: { private: true } },
    { path: '/account/password', name: 'password', component: PasswordView, meta: { private: true } },
    { path: '/admin/users', name: 'users', component: UserManagementView, meta: { private: true, admin: true } },
    {
      path: '/',
      name: 'agent-home',
      component: AgentHomeView,
    },
    {
      path: '/agents',
      name: 'agent-plaza',
      component: AgentPlazaView,
    },
    {
      path: '/agents/conversation-assistant',
      name: 'agent-conversation',
      meta: { private: true },
      component: AgentConversationView,
    },
    {
      path: '/agents/:agentId/flow',
      name: 'agent-flow',
      meta: { private: true },
      component: AgentFlowView,
    },
    {
      path: '/agents/:agentId',
      name: 'agent-workbench',
      meta: { private: true },
      component: AgentWorkbenchView,
    },
  ],
})

export function installAuthRouting(auth: AuthController) {
  router.beforeEach(async to => {
    if (auth.phase.value === 'unknown') await auth.bootstrap()
    if (!to.meta.private) return true
    if (['unconfirmed', 'checking'].includes(auth.phase.value)) return true
    if (!auth.user.value) return { name: 'login', replace: true }
    if (auth.phase.value === 'password-required' && to.name !== 'password') return { name: 'password', replace: true }
    if (to.meta.admin && auth.user.value.role !== 'admin') return { name: 'account', replace: true }
    return true
  })
}
