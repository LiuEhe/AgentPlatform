export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export interface SafeError { code: string; message: string }
export interface DocumentView { id: string; filename: string; chars: number }
export interface AgentCallView {
  id: string
  agent_id: string
  agent_name: string
  invocation_id: string | null
  status: RunStatus
  output_type: 'markdown' | 'text' | 'json' | null
  output: string | null
  error: SafeError | null
}
export interface MessageView {
  id: string
  sequence: number
  role: 'user' | 'assistant'
  content: string
  document_ids: string[]
  run_id: string | null
  agent_call: AgentCallView | null
}
export interface MessageCreate {
  client_message_id: string
  content: string
  document_ids: string[]
}
export interface RunView {
  id: string
  client_message_id: string
  status: RunStatus
  stage: string
  message: MessageView | null
  error: SafeError | null
}
export interface ConversationView {
  id: string
  expires_in_seconds: number
  messages: MessageView[]
  documents: DocumentView[]
  active_run_id: string | null
  last_sequence: number
}
export interface ConversationSummary { id: string; title: string }
export const isTerminal = (status: RunStatus) => ['succeeded', 'failed', 'cancelled'].includes(status)
