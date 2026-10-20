import { createRouter, createWebHistory } from 'vue-router'
import AgentHomeView from '../views/AgentHomeView.vue'
import AgentPlazaView from '../views/AgentPlazaView.vue'
import AgentWorkbenchView from '../views/AgentWorkbenchView.vue'
import AgentFlowView from '../views/AgentFlowView.vue'
import AgentConversationView from '../views/AgentConversationView.vue'

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
      path: '/agents/conversation-assistant',
      name: 'agent-conversation',
      component: AgentConversationView,
    },
    {
      path: '/agents/:agentId/flow',
      name: 'agent-flow',
      component: AgentFlowView,
    },
    {
      path: '/agents/:agentId',
      name: 'agent-workbench',
      component: AgentWorkbenchView,
    },
  ],
})
