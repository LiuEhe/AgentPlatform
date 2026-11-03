<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { changePassword } from '../../api/auth'
import { useAuth } from './useAuth'
const auth = useAuth(), router = useRouter()
const current = ref(''), password = ref(''), confirm = ref(''), busy = ref(false), error = ref('')
function clear() { current.value = ''; password.value = ''; confirm.value = '' }
onBeforeUnmount(clear)
async function submit() {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  if (password.value !== confirm.value) { error.value = '两次输入的新密码不一致。'; return }
  busy.value = true; error.value = ''
  try {
    await changePassword(current.value, password.value)
    if (auth.isCurrent(ticket)) { auth.invalidate('expired'); await router.replace('/login') }
  } catch (reason) { if (auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '修改失败，请重试。' }
  finally { clear(); if (auth.isCurrent(ticket)) busy.value = false }
}
</script>
<template>
  <form class="auth-card" @submit.prevent="submit">
    <h2>{{ auth.phase.value === 'password-required' ? '设置自己的密码' : '修改密码' }}</h2>
    <p class="auth-hint">修改成功后，所有登录会失效，请重新登录。</p>
    <label>当前密码<input v-model="current" required type="password" minlength="6" maxlength="20" autocomplete="current-password" :disabled="busy"></label>
    <label>新密码<input v-model="password" required type="password" minlength="6" maxlength="20" autocomplete="new-password" placeholder="6–20 个字符" :disabled="busy"></label>
    <label>确认新密码<input v-model="confirm" required type="password" minlength="6" maxlength="20" autocomplete="new-password" :disabled="busy"></label>
    <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
    <button class="button button-primary auth-submit" :disabled="busy">{{ busy ? '正在修改…' : '修改并重新登录' }}</button>
  </form>
</template>
