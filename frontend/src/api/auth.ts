import { apiRequest } from './client'
import type { AuthApi, AuthTicket, AuthView, LoginInput, RegisterInput, UserView } from '../features/auth/types'
const json = (value: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
export const authApi: AuthApi = {
  register: (input: RegisterInput) => apiRequest<UserView>('/api/v1/auth/register', json(input), 'json', 'public-auth'),
  login: (input: LoginInput) => apiRequest<AuthView>('/api/v1/auth/login', json(input), 'json', 'public-auth'),
  me: () => apiRequest<AuthView>('/api/v1/auth/me', {}, 'json', 'bootstrap'),
  logout: (ticket: AuthTicket) => apiRequest<void>('/api/v1/auth/logout', { method: 'POST' }, 'empty', 'bound', ticket),
}
export const changePassword = (current_password: string, new_password: string) =>
  apiRequest<void>('/api/v1/auth/password', json({ current_password, new_password }), 'empty')
