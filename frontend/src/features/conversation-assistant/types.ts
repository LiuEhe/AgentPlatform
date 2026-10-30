export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export interface SafeError { code: string; message: string }
export interface FileView { file_id: string; original_name: string; size_bytes: number; content_chars: number; created_at: string }
export interface AgentCallView {
  call_id: string
  agent_id: string
  agent_name: string
  invocation_id: string | null
  status: RunStatus
  output_type: 'markdown' | 'text' | 'json' | null
  output: string | null
  error: SafeError | null
}
export interface MessageView {
  message_id: string
  sequence: number
  created_at: string
  role: 'user' | 'assistant'
  content: string
  file_ids: string[]
  run_id: string | null
  agent_call: AgentCallView | null
}
export interface MessageCreate {
  client_message_id: string
  content: string
  file_ids: string[]
}
export interface RunView {
  run_id: string
  client_message_id: string
  status: RunStatus
  stage: string
  message: MessageView | null
  error: SafeError | null
}
export type RunEvent =
  | { event: 'snapshot'; run: RunView; text: string }
  | { event: 'delta'; text: string }
  | { event: 'state' | 'done'; run: RunView }
export interface SessionView extends SessionSummary {
  messages: MessageView[]
  files: FileView[]
  active_run_id: string | null
  last_sequence: number
  has_more: boolean
  next_before_sequence: number | null
  next_after_sequence: number | null
}
export interface SessionSummary { session_id: string; agent_id: string; title: string; created_at: string; updated_at: string }
export interface SessionListView { items: SessionSummary[]; next_cursor: string | null }
export const isTerminal = (status: RunStatus) => ['succeeded', 'failed', 'cancelled'].includes(status)
