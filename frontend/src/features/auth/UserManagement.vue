<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { LockKeyhole, X } from '@lucide/vue'
import { createUser, getUserProfile, listUsers, resetUserPassword, setUserStatus } from '../../api/users'
import { useAuth } from './useAuth'
import type { AuthTicket, UserProfile, UserView } from './types'
import UserAvatar from './UserAvatar.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
const auth = useAuth(), users = ref<UserView[]>([]), cursor = ref<string | null>(null)
const busy = ref(false), error = ref(''), message = ref(''), dialog = ref<HTMLDialogElement>()
const target = ref<UserView | null>(null), username = ref(''), name = ref(''), password = ref('')
const statusTarget = ref<{ user: UserView; ticket: AuthTicket } | null>(null)
watch(auth.epoch, () => { statusTarget.value = null })
let alive = true
const detailDialog = ref<HTMLDialogElement>(), detailProfile = ref<UserProfile | null>(null)
const detailBusy = ref(false), detailError = ref('')
let detailSequence = 0, detailController: AbortController | undefined
const genderNames = { male: '男', female: '女', other: '其他', undisclosed: '不愿透露' }
function closeDetails() {
  detailSequence++; detailController?.abort(); detailProfile.value = null
  detailDialog.value?.close()
}
onBeforeUnmount(closeDetails)
async function viewProfile(user: UserView) {
  const ticket = auth.capture(); if (!ticket) return
  const sequence = ++detailSequence
  detailController?.abort(); detailController = new AbortController()
  detailProfile.value = null; detailBusy.value = true; detailError.value = ''
  if (!detailDialog.value?.open) detailDialog.value?.showModal()
  try {
    const profile = await getUserProfile(user.user_id, detailController.signal)
    if (alive && sequence === detailSequence && auth.isCurrent(ticket)) detailProfile.value = profile
  } catch (reason) {
    if (alive && sequence === detailSequence && auth.isCurrent(ticket)) detailError.value = reason instanceof Error ? reason.message : '读取资料失败，请关闭后重试。'
  } finally { if (alive && sequence === detailSequence && auth.isCurrent(ticket)) detailBusy.value = false }
}
onBeforeUnmount(() => { alive = false; password.value = ''; dialog.value?.close() })
async function load(more = false) {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  busy.value = true; error.value = ''
  try {
    const page = await listUsers(more ? cursor.value ?? undefined : undefined)
    if (alive && auth.isCurrent(ticket)) { users.value = more ? [...users.value, ...page.items] : page.items; cursor.value = page.next_cursor }
  } catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '读取失败。' }
  finally { if (alive && auth.isCurrent(ticket)) busy.value = false }
}
onMounted(() => { void load() })
function open(user: UserView | null) {
  target.value = user; username.value = ''; name.value = ''; password.value = ''; error.value = ''; message.value = ''
  dialog.value?.showModal()
}
async function save() {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  busy.value = true; error.value = ''
  try {
    if (target.value) await resetUserPassword(target.value.user_id, password.value)
    else await createUser({ username: username.value, display_name: name.value, temporary_password: password.value })
    if (alive && auth.isCurrent(ticket)) { dialog.value?.close(); message.value = target.value ? '密码已重置，该用户需重新登录并修改临时密码。' : '普通用户已创建，首次登录需修改临时密码。' }
  } catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '保存失败。' }
  finally { password.value = ''; if (alive && auth.isCurrent(ticket)) busy.value = false }
  if (alive && auth.isCurrent(ticket) && !dialog.value?.open) await load()
}
function toggle(user: UserView) {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  statusTarget.value = { user: { ...user }, ticket }
}
async function confirmStatus() {
  const pending = statusTarget.value
  statusTarget.value = null
  if (!pending || !auth.capture() || !auth.isCurrent(pending.ticket) || busy.value) return
  const { user, ticket } = pending
  busy.value = true; error.value = ''
  try { await setUserStatus(user.user_id, user.status === 'active' ? 'disabled' : 'active') }
  catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '操作失败。' }
  finally { if (alive && auth.isCurrent(ticket)) busy.value = false }
  if (alive && auth.isCurrent(ticket)) await load()
}
</script>
<template>
  <div class="auth-management">
    <div class="auth-management-heading"><div><div class="eyebrow">管理员工作区</div><h1>用户管理</h1><p class="muted">管理账号与登录权限，保留每个人的私有历史。</p></div><button class="button button-primary" :disabled="busy" @click="open(null)">＋ 创建用户</button></div>
    <p v-if="error && !dialog?.open" class="auth-error" role="alert">{{ error }} <button class="text-button" @click="load()">重试</button></p>
    <p v-if="message" class="auth-success" role="status">{{ message }}</p>
    <div class="auth-table-wrap"><table class="auth-table"><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
      <tbody><tr v-for="user in users" :key="user.user_id"><td><strong>{{ user.display_name }}</strong><br><small>{{ user.username }}</small></td><td>{{ user.role === 'admin' ? '管理员' : '普通用户' }}</td><td><span class="badge">{{ user.status === 'active' ? '已启用' : '已停用' }}</span><small v-if="user.must_change_password"> · 需改密</small></td><td><button class="text-button" :data-profile-user="user.user_id" @click="viewProfile(user)">查看资料</button><span v-if="user.role === 'admin'" class="muted">内置管理员</span><div v-else class="account-menu"><button class="text-button" :disabled="busy" @click="toggle(user)">{{ user.status === 'active' ? '停用' : '启用' }}</button><button class="text-button" :disabled="busy" @click="open(user)">重置密码</button></div></td></tr></tbody>
    </table></div>
    <p v-if="busy" role="status">正在处理…</p><button v-if="cursor" class="button" :disabled="busy" @click="load(true)">加载更多</button>
    <p class="auth-note">这里只管理账号；管理员不能查看其他用户的对话正文。</p>
    <ConfirmDialog id="user-status" :open="statusTarget !== null" :title="statusTarget?.user.status === 'active' ? '停用账号？' : '启用账号？'"
      :confirm-label="statusTarget?.user.status === 'active' ? '停用账号' : '启用账号'" :variant="statusTarget?.user.status === 'active' ? 'danger' : 'default'"
      :subject="statusTarget?.user.username" subject-label="用户名" :busy="busy" @update:open="open => { if (!open) statusTarget = null }" @confirm="confirmStatus">
      <p>{{ statusTarget?.user.status === 'active' ? '停用后，该账号的所有登录立即失效。历史内容将保留。' : '启用后，该账号可以重新登录。历史内容保持不变。' }}</p>
    </ConfirmDialog>
    <dialog id="profile-dialog" ref="detailDialog" class="profile-detail-dialog" aria-labelledby="profile-dialog-title" @close="closeDetails">
      <div class="account-dialog-heading"><div><h2 id="profile-dialog-title">用户资料</h2><p>由用户本人维护</p></div><button type="button" class="icon-button" aria-label="关闭用户资料" @click="closeDetails"><X :size="20" /></button></div>
      <div class="profile-detail-body">
      <p v-if="detailBusy" role="status">正在读取资料…</p><p v-if="detailError" class="auth-error" role="alert">{{ detailError }}</p>
      <template v-if="detailProfile">
        <div class="profile-detail-person"><UserAvatar :user-id="detailProfile.user_id" :has-avatar="detailProfile.has_avatar" :revision="detailProfile.updated_at" :alt="detailProfile.display_name" /><div><strong>{{ detailProfile.display_name }}</strong><p>user_id: {{ detailProfile.username }}</p></div><span class="badge">{{ detailProfile.role === 'admin' ? '管理员' : '普通用户' }}</span></div>
        <dl class="profile-detail-fields"><div><dt>性别</dt><dd>{{ detailProfile.gender ? genderNames[detailProfile.gender] : '未填写' }}</dd></div><div><dt>生日</dt><dd>{{ detailProfile.birthday || '未填写' }}</dd></div><div class="profile-wide"><dt>个性签名</dt><dd>{{ detailProfile.bio || '未填写' }}</dd></div><div><dt>邮箱</dt><dd>{{ detailProfile.email || '未填写' }}</dd></div><div><dt>手机号</dt><dd>{{ detailProfile.phone_number || '未填写' }}</dd></div><div class="profile-wide"><dt>地址</dt><dd>{{ detailProfile.address || '未填写' }}</dd></div></dl>
      </template>
      </div><div class="account-dialog-actions"><span class="profile-detail-readonly"><LockKeyhole :size="14" aria-hidden="true" />只读资料</span><button type="button" class="button" @click="closeDetails">关闭</button></div>
    </dialog>
    <dialog ref="dialog" class="auth-dialog" aria-labelledby="user-dialog-title" @close="password = ''">
      <form @submit.prevent="save"><h2 id="user-dialog-title">{{ target ? '重置密码' : '创建普通用户' }}</h2>
        <template v-if="!target"><label>用户名<input v-model="username" required minlength="3" maxlength="32" :disabled="busy"></label><label>显示名称<input v-model="name" required maxlength="50" :disabled="busy"></label></template>
        <p v-else>{{ target.display_name }} · {{ target.username }}</p>
        <label>临时密码<input v-model="password" required type="password" minlength="6" maxlength="20" autocomplete="new-password" :disabled="busy"></label>
        <p class="auth-note">首次登录需要修改密码。密码不会在页面中再次展示。</p><p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <div class="account-menu"><button class="button button-primary" :disabled="busy">{{ target ? '重置密码' : '创建用户' }}</button><button class="button" type="button" :disabled="busy" @click="dialog?.close()">取消</button></div>
      </form>
    </dialog>
  </div>
</template>
