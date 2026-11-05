import { apiRequest } from './client'
import type { ProfilePatch, UserProfile, UserView } from '../features/auth/types'
const json = (method: string, value: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
export const getProfile = (signal?: AbortSignal) => apiRequest<UserProfile>('/api/v1/users/me', { signal })
export const updateProfile = (input: ProfilePatch, signal?: AbortSignal) => apiRequest<UserProfile>('/api/v1/users/me', { ...json('PATCH', input), signal })
export const getUserProfile = (id: string, signal?: AbortSignal) => apiRequest<UserProfile>(`/api/v1/admin/users/${encodeURIComponent(id)}`, { signal })
export const uploadAvatar = (file: File, signal?: AbortSignal) => {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<UserProfile>('/api/v1/users/me/avatar', { method: 'POST', body, signal })
}
export const removeAvatar = (signal?: AbortSignal) => apiRequest<void>('/api/v1/users/me/avatar', { method: 'DELETE', signal }, 'empty')
export const getAvatar = (targetUserId?: string, signal?: AbortSignal) => apiRequest<Blob>(targetUserId
  ? `/api/v1/admin/users/${encodeURIComponent(targetUserId)}/avatar` : '/api/v1/users/me/avatar', { signal }, 'blob')
export const listUsers = (cursor?: string) => apiRequest<{ items: UserView[]; next_cursor: string | null }>(`/api/v1/admin/users?limit=20${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`)
export const createUser = (input: { username: string; display_name: string; temporary_password: string }) => apiRequest<UserView>('/api/v1/admin/users', json('POST', input))
export const setUserStatus = (id: string, status: 'active' | 'disabled') => apiRequest<UserView>(`/api/v1/admin/users/${encodeURIComponent(id)}`, json('PATCH', { status }))
export const resetUserPassword = (id: string, temporary_password: string) => apiRequest<void>(`/api/v1/admin/users/${encodeURIComponent(id)}/password-reset`, json('POST', { temporary_password }), 'empty')
