import { createApp, watch } from 'vue'
import './style.css'
import App from './App.vue'
import { router, installAuthRouting } from './router'
import { authKey, createAuthController } from './features/auth/useAuth'
import { authApi } from './api/auth'
import { installAuthHooks } from './api/client'

const auth = createAuthController(authApi)
installAuthHooks({ capture: auth.capture, isCurrent: auth.isCurrent, onAuthError(error) {
  if (error.status === 401) auth.invalidate('expired')
  else if (error.code === 'AUTH_CONTEXT_CHANGED') auth.invalidate('context-changed')
  else if (error.code === 'PASSWORD_CHANGE_REQUIRED') { auth.invalidate('password-required'); void auth.revalidate() }
  else if (error.code === 'STORAGE_UNAVAILABLE') void auth.revalidate()
} })
installAuthRouting(auth)
watch(auth.phase, phase => {
  if (!router.currentRoute.value.meta.private) return
  if (['anonymous', 'logout-pending'].includes(phase)) void router.replace('/login')
  else if (phase === 'password-required' && router.currentRoute.value.name !== 'password') void router.replace('/account/password')
})
createApp(App).provide(authKey, auth).use(router).mount('#app')
