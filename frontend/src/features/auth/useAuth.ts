import { inject, nextTick, readonly, ref, type InjectionKey } from 'vue'
import { ApiError } from '../../api/client'
import type { AuthApi, AuthController, AuthInvalidation, AuthPhase, AuthTicket, AuthView, UserView } from './types'

export const authKey: InjectionKey<AuthController> = Symbol('platform-auth')
const LOCK = 'agent-platform-logout-lock'
const SIGNAL = 'agent-platform-identity-signal'
export function createAuthController(api: AuthApi): AuthController {
  const phase = ref<AuthPhase>('unknown'), user = ref<UserView | null>(null), epoch = ref(0)
  const storageAvailable = ref(true)
  let context: AuthView | null = null, operation = 0, pendingLogout: AuthTicket | null = null
  let lock: string | null = null
  let initialRestore = true
  let expiryTimer: ReturnType<typeof setTimeout> | undefined
  const cleanups = new Set<() => void>()
  const listeners: (() => void)[] = []
  function cloak() { if (typeof document !== 'undefined') document.documentElement?.classList.add('identity-unconfirmed') }
  function reveal() { void nextTick(() => {
    if (['authenticated', 'password-required', 'anonymous'].includes(phase.value) && typeof document !== 'undefined') document.documentElement?.classList.remove('identity-unconfirmed')
  }) }
  function storage(action: () => void) { try { action() } catch { storageAvailable.value = false } }
  function clearPrivate(preserveUserId?: string) {
    cloak()
    initialRestore = false
    epoch.value++
    clearTimeout(expiryTimer)
    cleanups.forEach(fn => fn())
    storage(() => {
      if (typeof sessionStorage === 'undefined') return
      const retained = new Set(preserveUserId ? ['agent-platform-session', 'agent-platform-session-pending-id', 'agent-platform-session-deletions'].map(key => `${key}:${preserveUserId}`) : [])
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('agent-platform-session') && !retained.has(key)) sessionStorage.removeItem(key)
      }
      for (const key of ['agent-platform-session', 'agent-platform-session-pending-id', 'agent-platform-session-deletions']) sessionStorage.removeItem(key)
    })
    context = null; user.value = null
  }
  function capture(): AuthTicket | null {
    if (!context || !['authenticated', 'password-required'].includes(phase.value)) return null
    return { epoch: epoch.value, userId: context.user.user_id, authSessionId: context.auth_session_id, csrfToken: context.csrf_token }
  }
  function isCurrent(ticket: AuthTicket) {
    return ticket.epoch === epoch.value && context?.user.user_id === ticket.userId && context?.auth_session_id === ticket.authSessionId
  }
  function broadcast() {
    storage(() => { if (typeof localStorage !== 'undefined') localStorage.setItem(SIGNAL, crypto.randomUUID()) })
  }
  function hasLock() {
    let found = lock !== null
    storage(() => { if (typeof localStorage !== 'undefined') found = localStorage.getItem(LOCK) !== null })
    return found
  }
  function accept(next: AuthView) {
    if (!context) clearPrivate(initialRestore ? next.user.user_id : undefined)
    else if (context.user.user_id !== next.user.user_id || context.auth_session_id !== next.auth_session_id) clearPrivate()
    context = next; user.value = next.user
    phase.value = next.user.must_change_password ? 'password-required' : 'authenticated'
    clearTimeout(expiryTimer)
    expiryTimer = setTimeout(() => invalidate('expired'), Math.max(0, Date.parse(next.expires_at) - Date.now()))
    reveal()
  }
  function invalidate(reason: AuthInvalidation) {
    operation++
    if (reason === 'password-required' && context) {
      clearPrivate(); phase.value = 'anonymous'
    } else { clearPrivate(); phase.value = hasLock() ? 'logout-pending' : 'anonymous' }
    reveal()
  }
  async function revalidate() {
    if (hasLock()) { clearPrivate(); phase.value = 'logout-pending'; return }
    const op = ++operation
    cloak()
    phase.value = 'checking'
    try {
      const next = await api.me()
      if (op === operation && !hasLock()) accept(next)
    } catch (error) {
      if (op !== operation) return
      if (error instanceof ApiError && error.status === 401) invalidate('expired')
      else phase.value = 'unconfirmed'
    }
  }
  async function login(input: { username: string; password: string }) {
    const op = ++operation
    clearPrivate(); phase.value = 'checking'
    try {
      const granted = await api.login(input)
      const actual = await api.me()
      if (op !== operation) return
      if (actual.auth_session_id !== granted.auth_session_id || actual.user.user_id !== granted.user.user_id) {
        invalidate('context-changed'); throw new Error('登录状态已变化，请重新登录。')
      }
      lock = null; pendingLogout = null
      storage(() => { if (typeof localStorage !== 'undefined') localStorage.removeItem(LOCK) })
      accept(actual); broadcast()
    } catch (error) {
      if (op === operation) phase.value = hasLock() ? 'logout-pending' : 'anonymous'
      reveal()
      throw error
    }
  }
  async function logout() {
    const original = pendingLogout ?? (context ? {
      epoch: epoch.value, userId: context.user.user_id,
      authSessionId: context.auth_session_id, csrfToken: context.csrf_token,
    } : null)
    if (!original) { invalidate('logout'); return }
    const retry = pendingLogout !== null
    pendingLogout = original
    const logoutOperation = ++operation
    clearPrivate()
    lock ??= crypto.randomUUID()
    const ownLock = lock
    storage(() => { if (typeof localStorage !== 'undefined') localStorage.setItem(LOCK, ownLock!) })
    phase.value = 'logout-pending'; broadcast()
    try {
      if (retry) {
        const actual = await api.me()
        if (actual.auth_session_id !== original.authSessionId || actual.user.user_id !== original.userId) return
      }
      await api.logout(original)
      if (lock !== ownLock || operation !== logoutOperation) return
      storage(() => { if (typeof localStorage !== 'undefined' && localStorage.getItem(LOCK) === ownLock) localStorage.removeItem(LOCK) })
      lock = null; pendingLogout = null; phase.value = 'anonymous'; broadcast()
      reveal()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401 && lock === ownLock && operation === logoutOperation) {
        lock = null; pendingLogout = null
        storage(() => { if (typeof localStorage !== 'undefined' && localStorage.getItem(LOCK) === ownLock) localStorage.removeItem(LOCK) })
        phase.value = 'anonymous'
        reveal()
      }
    }
  }
  if (typeof window !== 'undefined') {
    const changed = (event: StorageEvent) => {
      if (event.key !== SIGNAL && event.key !== LOCK) return
      invalidate('context-changed')
      if (!hasLock() && !document.hidden) void revalidate()
    }
    const hidden = () => { if (document.hidden) { cloak(); operation++; if (context) phase.value = 'unconfirmed' } else void revalidate() }
    const pagehide = () => { cloak(); operation++; if (context) phase.value = 'unconfirmed' }
    const pageshow = () => { void revalidate() }
    window.addEventListener('storage', changed); document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', pagehide); window.addEventListener('pageshow', pageshow)
    listeners.push(() => { window.removeEventListener('storage', changed); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', pagehide); window.removeEventListener('pageshow', pageshow) })
  }
  return { phase: readonly(phase), user: readonly(user), epoch: readonly(epoch), storageAvailable: readonly(storageAvailable),
    capture, isCurrent, login, logout, bootstrap: revalidate, revalidate, invalidate,
    registerCleanup(fn) { cleanups.add(fn); return () => cleanups.delete(fn) },
    dispose() { clearTimeout(expiryTimer); listeners.forEach(fn => fn()); cleanups.clear() } }
}
export function useAuth(): AuthController {
  const auth = inject(authKey)
  if (!auth) throw new Error('Authentication controller is not installed')
  return auth
}
