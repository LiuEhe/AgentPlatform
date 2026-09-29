import { createRouter, createWebHistory } from 'vue-router'
import AgentHomeView from '../views/AgentHomeView.vue'
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
      path: '/agents/:agentId',
      name: 'agent-workbench',
      component: AgentWorkbenchView,
    },
  ],
})
