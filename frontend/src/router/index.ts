import { createRouter, createWebHistory } from 'vue-router'
import AgentHomeView from '../views/AgentHomeView.vue'
import AgentPlazaView from '../views/AgentPlazaView.vue'
import AgentWorkbenchView from '../views/AgentWorkbenchView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
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
      path: '/agents/:agentId',
      name: 'agent-workbench',
      component: AgentWorkbenchView,
    },
  ],
})
