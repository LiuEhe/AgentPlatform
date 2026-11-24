import { ApiError } from '../../api/client'
import { getSessionRun, subscribeSessionRun } from '../../api/conversations'
import { isTerminal, type RunEvent } from './types'

type ConversationStreamOptions = {
  signal: AbortSignal
  isCurrent: () => boolean
  onEvent: (event: RunEvent) => void
  onReconnecting: (reconnecting: boolean) => void
  onDisconnected: (reason: unknown, expired: boolean) => void
}

export function createConversationStream() {
  let version = 0
  let unsubscribe: (() => void) | undefined

  function close() {
    version += 1
    unsubscribe?.()
    unsubscribe = undefined
  }

  function open(id: string, runId: string, options: ConversationStreamOptions) {
    close()
    const current = version
    let reconnecting = false
    const valid = () => current === version && options.isCurrent()

    async function disconnected(reason: unknown) {
      if (!valid()) return
      close()
      const recoveryVersion = version
      const recoveryValid = () => recoveryVersion === version && options.isCurrent()
      try {
        const run = await getSessionRun(id, runId, options.signal)
        if (!recoveryValid()) return
        options.onEvent({ event: 'state', run })
        if (!isTerminal(run.status)) options.onDisconnected(reason, false)
      } catch (failure) {
        if (!recoveryValid() || options.signal.aborted) return
        options.onDisconnected(failure, failure instanceof ApiError && failure.status === 404)
      }
    }

    try {
      const stop = subscribeSessionRun(id, runId, {
        onEvent(event) {
          if (!valid()) return
          if (reconnecting) { reconnecting = false; options.onReconnecting(false) }
          options.onEvent(event)
        },
        onReconnecting() {
          if (!valid()) return
          reconnecting = true
          options.onReconnecting(true)
        },
        onError: reason => { void disconnected(reason) },
      }, options.signal)
      if (valid()) unsubscribe = stop
      else stop()
    } catch (reason) { void disconnected(reason) }
  }

  return {
    open, close,
    get version() { return version },
    get connected() { return unsubscribe !== undefined },
  }
}
