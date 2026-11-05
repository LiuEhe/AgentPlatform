import type { FileView, MessageCreate, MessageView, RunView } from './types'

export type RetryAction = 'initialize' | 'create' | 'send' | 'stream' | 'refresh' | 'switch' | null

interface ConversationSnapshot {
  messages: MessageView[]
  files: FileView[]
  selectedIds: string[]
  draft: string
  run: RunView | null
  pending: MessageCreate | null
  retryAction: RetryAction
  retryTarget: string | null
  error: string
  streamingText: string
  earlierCursor: number | null
  receivedSequence: number
}

export class ConversationSnapshots {
  private readonly snapshots = new Map<string, ConversationSnapshot>()

  save(id: string, value: ConversationSnapshot) {
    this.snapshots.set(id, {
      ...value, messages: [...value.messages], files: [...value.files], selectedIds: [...value.selectedIds],
    })
  }

  restore(id: string | null): ConversationSnapshot {
    const value = id ? this.snapshots.get(id) : undefined
    return {
      messages: [...(value?.messages ?? [])], files: [...(value?.files ?? [])],
      selectedIds: [...(value?.selectedIds ?? [])], draft: value?.draft ?? '', run: value?.run ?? null,
      pending: value?.pending ?? null, retryAction: value?.retryAction ?? null,
      retryTarget: value?.retryTarget ?? null, error: value?.error ?? '',
      streamingText: value?.streamingText ?? '', earlierCursor: value?.earlierCursor ?? null,
      receivedSequence: value?.receivedSequence ?? 0,
    }
  }

  hasDraft(id: string) { return Boolean(this.snapshots.get(id)?.draft) }

  discard(id: string) { this.snapshots.delete(id) }

  invalidate(id: string) {
    this.snapshots.delete(id)
    for (const snapshot of this.snapshots.values()) {
      if (snapshot.retryTarget === id) { snapshot.retryTarget = null; snapshot.retryAction = null }
    }
  }

  clear() { this.snapshots.clear() }
}
