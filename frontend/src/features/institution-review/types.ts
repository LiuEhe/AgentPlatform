export type ReviewStatus = 'idle' | 'submitting' | 'success' | 'error'

export type ReviewMode = 'knowledge_base' | 'standard_document'

export type ReviewSubmission =
  | { mode: 'knowledge_base'; file: File }
  | { mode: 'standard_document'; file: File; standardFile: File }

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
