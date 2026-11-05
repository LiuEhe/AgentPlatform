<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ChevronDown, KeyRound, LogOut, UserRound, UsersRound, X } from '@lucide/vue'
import { useAuth } from './useAuth'
import UserAvatar from './UserAvatar.vue'
const auth = useAuth(), router = useRouter()
const dropdown = ref<HTMLDetailsElement>(), logoutDialog = ref<HTMLDialogElement>(), busy = ref(false)
function closeMenu() { if (dropdown.value) dropdown.value.open = false }
function focusTrigger() { dropdown.value?.querySelector('summary')?.focus() }
function dismissMenu() { closeMenu(); focusTrigger() }
function outside(event: PointerEvent) { if (!dropdown.value?.contains(event.target as Node)) closeMenu() }
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); logoutDialog.value?.close() })
watch(auth.phase, closeMenu)
function askLogout() { dismissMenu(); logoutDialog.value?.showModal() }
async function logout() {
  if (busy.value) return
  busy.value = true
  try { logoutDialog.value?.close(); await auth.logout(); await router.replace('/login') }
  finally { busy.value = false }
}
</script>
<template>
  <div class="account-menu account-control">
    <template v-if="auth.user.value">
      <details ref="dropdown" class="account-dropdown" @keydown.esc.stop.prevent="dismissMenu">
        <summary aria-label="打开账号菜单"><UserAvatar :has-avatar="auth.user.value.has_avatar" :revision="auth.user.value.updated_at" :alt="auth.user.value.display_name" /><span class="account-trigger-name">{{ auth.user.value.display_name }}</span><ChevronDown :size="14" aria-hidden="true" /></summary>
        <div class="account-dropdown-panel"><div class="account-dropdown-identity"><strong>{{ auth.user.value.display_name }}</strong><small>{{ auth.user.value.username }} · {{ auth.user.value.role === 'admin' ? '管理员' : '普通用户' }}</small></div>
          <RouterLink to="/account" @click="closeMenu"><UserRound :size="16" aria-hidden="true" />个人资料</RouterLink>
          <RouterLink to="/account/password" @click="closeMenu"><KeyRound :size="16" aria-hidden="true" />修改密码</RouterLink>
          <RouterLink v-if="auth.user.value.role === 'admin'" to="/admin/users" @click="closeMenu"><UsersRound :size="16" aria-hidden="true" />用户管理</RouterLink>
          <button id="account-logout-trigger" class="account-logout" type="button" @click="askLogout"><LogOut :size="16" aria-hidden="true" />退出登录</button>
        </div>
      </details>
      <dialog ref="logoutDialog" class="account-confirm-dialog" aria-labelledby="account-logout-title" @close="focusTrigger"><div class="account-dialog-heading"><h2 id="account-logout-title">退出登录？</h2><button type="button" class="icon-button" aria-label="取消退出登录" @click="logoutDialog?.close()"><X :size="20" /></button></div><p class="account-confirm-body">退出后，未发送的会话草稿、附件选择和本页未保存的更改将被清除。</p><div class="account-dialog-actions"><button id="account-logout-cancel" class="button" type="button" @click="logoutDialog?.close()">取消</button><button id="account-logout-confirm" class="button account-primary" type="button" :disabled="busy" @click="logout">退出登录</button></div></dialog>
    </template>
    <RouterLink v-else to="/login">登录</RouterLink>
  </div>
</template>
