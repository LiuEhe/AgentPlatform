<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { authApi } from '../../api/auth'
import { useAuth } from './useAuth'
const auth = useAuth()
const username = ref(''), displayName = ref(''), password = ref(''), error = ref(''), busy = ref(false), success = ref(false)
let mounted = true
onBeforeUnmount(() => { mounted = false; password.value = '' })
async function submit() {
  if (busy.value) return
  const epoch = auth.epoch.value
  busy.value = true; error.value = ''
  try {
    await authApi.register({ username: username.value, display_name: displayName.value, password: password.value })
    if (mounted && epoch === auth.epoch.value) success.value = true
  } catch (reason) { if (mounted && epoch === auth.epoch.value) error.value = reason instanceof Error ? reason.message : '注册失败，请重试。' }
  finally { password.value = ''; busy.value = false }
}
</script>
<template>
  <form class="auth-card" @submit.prevent="submit">
    <h2>创建账号</h2><p class="muted">设置你的用户名和密码。</p>
    <template v-if="!success">
      <label>用户名<input v-model="username" required minlength="3" maxlength="32" autocomplete="username" placeholder="3–32 位字母、数字或下划线" :disabled="busy"></label>
      <label>显示名称<input v-model="displayName" required maxlength="50" autocomplete="nickname" placeholder="希望如何称呼你" :disabled="busy"></label>
      <label>密码<input v-model="password" required type="password" minlength="6" maxlength="20" autocomplete="new-password" placeholder="6–20 个字符" :disabled="busy"></label>
      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
      <button class="button button-primary auth-submit" :disabled="busy">{{ busy ? '正在创建…' : '创建账号' }}</button>
    </template>
    <p v-else class="auth-success" role="status">账号已创建。{{ auth.user.value ? '当前登录保持不变；如需使用新账号，请先退出。' : '请使用新账号登录。' }}</p>
    <p class="auth-note">{{ success ? '开始使用' : '已有账号？' }} <RouterLink to="/login">去登录</RouterLink></p>
  </form>
</template>
