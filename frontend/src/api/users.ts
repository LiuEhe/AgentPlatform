import { apiRequest } from './client'
import type { UserView } from '../features/auth/types'
const json = (method: string, value: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
export const updateProfile = (display_name: string) => apiRequest<UserView>('/api/v1/users/me', json('PATCH', { display_name }))
export const listUsers = (cursor?: string) => apiRequest<{ items: UserView[]; next_cursor: string | null }>(`/api/v1/admin/users?limit=20${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`)
export const createUser = (input: { username: string; display_name: string; temporary_password: string }) => apiRequest<UserView>('/api/v1/admin/users', json('POST', input))
export const setUserStatus = (id: string, status: 'active' | 'disabled') => apiRequest<UserView>(`/api/v1/admin/users/${encodeURIComponent(id)}`, json('PATCH', { status }))
export const resetUserPassword = (id: string, temporary_password: string) => apiRequest<void>(`/api/v1/admin/users/${encodeURIComponent(id)}/password-reset`, json('POST', { temporary_password }), 'empty')
