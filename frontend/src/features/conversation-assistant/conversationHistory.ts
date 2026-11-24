import type { MessageView, SessionSummary } from './types'

export function mergeMessages(current: MessageView[], incoming: MessageView[]) {
  const indexed = new Map(current.map(message => [message.message_id, message]))
  incoming.forEach(message => indexed.set(message.message_id, message))
  return [...indexed.values()].sort((a, b) => a.sequence - b.sequence)
}

export function mergeSessions(current: SessionSummary[], incoming: SessionSummary[], deleted: Set<string>) {
  const indexed = new Map(current.map(item => [item.session_id, item]))
  incoming.forEach(item => { if (!deleted.has(item.session_id)) indexed.set(item.session_id, item) })
  return [...indexed.values()].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at) || b.session_id.localeCompare(a.session_id),
  )
}
