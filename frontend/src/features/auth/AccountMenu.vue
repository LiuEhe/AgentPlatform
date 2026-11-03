<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useAuth } from './useAuth'
const auth = useAuth(), router = useRouter()
async function logout() {
  if (!window.confirm('退出登录会清除未发送的草稿、附件选择和当前页面内容，是否继续？')) return
  await auth.logout()
  await router.replace('/login')
}
</script>
<template>
  <div class="account-menu">
    <template v-if="auth.user.value">
      <RouterLink to="/account">{{ auth.user.value.display_name }}</RouterLink>
      <RouterLink v-if="auth.user.value.role === 'admin'" to="/admin/users">用户管理</RouterLink>
      <button class="text-button" type="button" @click="logout">退出</button>
    </template>
    <RouterLink v-else to="/login">登录</RouterLink>
  </div>
</template>
