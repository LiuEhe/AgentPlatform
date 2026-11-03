import { apiRequest } from './client'
import type { AgentGraph } from '../features/institution-review/types'

export interface AgentMetadata { agent_id: string; name: string; description: string }

export const listAgents = () => apiRequest<AgentMetadata[]>('/api/v1/agents', {}, 'json', 'bootstrap')
export const getAgentGraph = (agentId: string) => apiRequest<AgentGraph>(`/api/v1/agents/${encodeURIComponent(agentId)}/graph`)
