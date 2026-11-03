import type { Ref } from 'vue'

export interface UserView {
  user_id: string
  username: string
  display_name: string
  role: 'admin' | 'user'
  status: 'active' | 'disabled'
  must_change_password: boolean
  created_at: string
  updated_at: string
}
export interface AuthView { user: UserView; auth_session_id: string; csrf_token: string; expires_at: string }
export interface LoginInput { username: string; password: string }
export interface RegisterInput extends LoginInput { display_name: string }
export interface AuthTicket { epoch: number; userId: string; authSessionId: string; csrfToken: string }
export type AuthInvalidation = 'logout' | 'expired' | 'password-required' | 'context-changed'
export type AuthPhase = 'unknown' | 'checking' | 'authenticated' | 'password-required' | 'anonymous' | 'logout-pending' | 'unconfirmed'
export interface AuthApi {
  register(input: RegisterInput): Promise<UserView>
  login(input: LoginInput): Promise<AuthView>
  me(): Promise<AuthView>
  logout(ticket: AuthTicket): Promise<void>
}
export interface AuthController {
  phase: Readonly<Ref<AuthPhase>>
  user: Readonly<Ref<UserView | null>>
  epoch: Readonly<Ref<number>>
  storageAvailable: Readonly<Ref<boolean>>
  bootstrap(): Promise<void>
  revalidate(): Promise<void>
  login(input: LoginInput): Promise<void>
  logout(): Promise<void>
  invalidate(reason: AuthInvalidation): void
  capture(): AuthTicket | null
  isCurrent(ticket: AuthTicket): boolean
  registerCleanup(fn: () => void): () => void
  dispose(): void
}
