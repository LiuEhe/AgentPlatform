<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { updateProfile } from '../../api/users'
import { useAuth } from './useAuth'
const auth = useAuth(), name = ref(auth.user.value?.display_name ?? ''), busy = ref(false), message = ref('')
async function save() {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  busy.value = true; message.value = ''
  try { await updateProfile(name.value); if (auth.isCurrent(ticket)) { await auth.revalidate(); message.value = '显示名称已保存。' } }
  catch (error) { if (auth.isCurrent(ticket)) message.value = error instanceof Error ? error.message : '保存失败，请重试。' }
  finally { if (auth.isCurrent(ticket)) busy.value = false }
}
</script>
<template>
  <form class="auth-card" @submit.prevent="save">
    <div class="row"><h2>个人资料</h2><span class="badge">{{ auth.user.value?.role === 'admin' ? '管理员' : '普通用户' }}</span></div>
    <label>用户名<input :value="auth.user.value?.username" readonly></label>
    <label>显示名称<input v-model="name" required maxlength="50" :disabled="busy"></label>
    <p v-if="message" role="status">{{ message }}</p>
    <button class="button button-primary auth-submit" :disabled="busy">保存名称</button>
    <p class="auth-note"><RouterLink to="/account/password">修改密码</RouterLink></p>
  </form>
</template>
