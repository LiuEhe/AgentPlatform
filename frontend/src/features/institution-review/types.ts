export type ReviewStatus = 'idle' | 'submitting' | 'success' | 'error'

export interface AgentGraphNode {
  id: string
  label: string
}

export interface AgentGraphEdge {
  sources: string[]
  target: string
}

export interface AgentGraph {
  agent_id: string
  name: string
  nodes: AgentGraphNode[]
  edges: AgentGraphEdge[]
}
