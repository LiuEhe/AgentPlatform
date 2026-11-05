import { createApp, watch } from 'vue'
// Keep feature styles eager and ordered; navigation must not change the cascade.
import './features/auth/auth.css'
import './style.css'
import './views/public-pages.css'
import './features/conversation-assistant/conversation.css'
import './features/institution-review/review.css'
import './features/auth/account.css'
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
