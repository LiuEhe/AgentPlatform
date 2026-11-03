<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useAuth } from './useAuth'
const auth = useAuth(), router = useRouter()
const username = ref(''), password = ref(''), error = ref(''), busy = ref(false)
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    await auth.login({ username: username.value, password: password.value })
    password.value = ''
    if (auth.capture()) await router.replace(auth.phase.value === 'password-required' ? '/account/password' : '/agents')
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '登录失败，请重试。' }
  finally { password.value = ''; busy.value = false }
}
</script>
<template>
  <form class="auth-card" @submit.prevent="submit">
    <h2>欢迎回来</h2><p class="muted">登录以继续你的工作。</p>
    <label>用户名<input v-model="username" required maxlength="32" autocomplete="username" placeholder="输入用户名" :disabled="busy"></label>
    <label>密码<input v-model="password" required type="password" minlength="6" maxlength="20" autocomplete="current-password" placeholder="6–20 个字符" :disabled="busy"></label>
    <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
    <button class="button button-primary auth-submit" :disabled="busy">{{ busy ? '正在登录…' : '登录' }}</button>
    <p class="auth-note">还没有账号？ <RouterLink to="/register">创建账号</RouterLink></p>
  </form>
</template>
