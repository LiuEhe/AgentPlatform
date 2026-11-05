<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink, onBeforeRouteLeave } from 'vue-router'
import { Pencil } from '@lucide/vue'
import { ApiError } from '../../api/client'
import { getProfile, updateProfile, uploadAvatar } from '../../api/users'
import type { AuthTicket, Gender, ProfilePatch, UserProfile } from './types'
import UserAvatar from './UserAvatar.vue'
import AvatarCropper from './AvatarCropper.vue'
import { useAuth } from './useAuth'
const auth = useAuth(), baseline = ref<UserProfile | null>(null)
const draft = reactive({ display_name: '', email: '', gender: '' as Gender | '', birthday: '', phone_number: '', address: '', bio: '' })
const loading = ref(false), busy = ref(false), message = ref(''), error = ref('')
const fields = ref<Record<string, string>>({}), avatarRevision = ref(0)
const avatarUnconfirmed = ref(false)
const avatarInput = ref<HTMLInputElement>(), cropFile = ref<File>()
let cropTicket: AuthTicket | null = null
const controller = new AbortController()
let alive = true
const today = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10)
const birthdayMax = ref(today())
const keys = ['display_name', 'email', 'gender', 'birthday', 'phone_number', 'address', 'bio'] as const
const dirty = computed(() => !!baseline.value && keys.some(key => (draft[key].trim() || (key === 'display_name' ? '' : null)) !== baseline.value?.[key]))
onBeforeRouteLeave(() => !dirty.value || window.confirm('离开后，本页尚未保存的资料更改将被放弃。头像更新不受影响，是否继续？'))
function accept(profile: UserProfile) {
  baseline.value = profile
  avatarUnconfirmed.value = false
  for (const key of keys) Object.assign(draft, { [key]: profile[key] ?? '' })
}
async function load() {
  const ticket = auth.capture(); if (!ticket) return
  loading.value = true; error.value = ''
  try { const profile = await getProfile(controller.signal); if (alive && auth.isCurrent(ticket)) accept(profile) }
  catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '读取资料失败。' }
  finally { if (alive && auth.isCurrent(ticket)) loading.value = false }
}
onMounted(() => { void load() })
onBeforeUnmount(() => { alive = false; controller.abort() })
function changes(): ProfilePatch | null {
  fields.value = {}
  const limits = { display_name: 50, email: 254, phone_number: 32, address: 500, bio: 200 }
  for (const [key, limit] of Object.entries(limits)) {
    if (Array.from(draft[key as keyof typeof draft].trim()).length > limit) fields.value[key] = `最多${limit}个字符。`
  }
  if (!draft.display_name.trim()) fields.value.display_name = '请输入显示名称。'
  if (draft.birthday && draft.birthday > today()) fields.value.birthday = '生日不能晚于今天。'
  if (draft.phone_number.trim() && (!/^\+?[0-9 ()-]+$/.test(draft.phone_number.trim()) || !/[0-9]/.test(draft.phone_number))) fields.value.phone_number = '手机号格式无效。'
  if (Object.keys(fields.value).length) return null
  const patch: ProfilePatch = {}
  for (const key of keys) {
    const value = key === 'display_name' ? draft[key].trim() : draft[key].trim() || null
    if (value !== baseline.value?.[key]) Object.assign(patch, { [key]: value })
  }
  return patch
}
async function save() {
  const ticket = auth.capture(); if (!ticket || busy.value || !baseline.value) return
  const patch = changes(); if (!patch) return
  if (!Object.keys(patch).length) return
  busy.value = true; message.value = ''; error.value = ''
  try {
    const profile = await updateProfile(patch, controller.signal)
    if (alive && auth.isCurrent(ticket)) { accept(profile); await auth.revalidate(); if (alive && auth.isCurrent(ticket)) message.value = '个人资料已保存。' }
  } catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '保存失败，请重试。' }
  finally { if (alive && auth.isCurrent(ticket)) busy.value = false }
}
async function avatar(file: File) {
  const ticket = auth.capture(); if (!ticket || busy.value || !baseline.value) return
  busy.value = true; message.value = ''; error.value = ''
  try {
    const profile = await uploadAvatar(file, controller.signal)
    if (alive && auth.isCurrent(ticket) && baseline.value) Object.assign(baseline.value, { has_avatar: profile.has_avatar, updated_at: profile.updated_at })
    if (alive && auth.isCurrent(ticket)) { avatarRevision.value++; await auth.revalidate(); if (alive && auth.isCurrent(ticket)) message.value = '头像已保存。' }
  } catch (reason) {
    if (alive && auth.isCurrent(ticket)) {
      error.value = reason instanceof Error ? reason.message : '头像保存失败。'
      if (!(reason instanceof ApiError) || reason.status >= 500) {
        avatarUnconfirmed.value = true
        try { await refreshAvatar(ticket) }
        catch { if (alive && auth.isCurrent(ticket)) error.value += ' 头像状态尚未确认，请重新确认。' }
      }
    }
  }
  finally { if (alive && auth.isCurrent(ticket)) busy.value = false }
}
async function refreshAvatar(ticket: AuthTicket) {
  const profile = await getProfile(controller.signal)
  if (!alive || !auth.isCurrent(ticket) || !baseline.value) return
  Object.assign(baseline.value, { has_avatar: profile.has_avatar, updated_at: profile.updated_at })
  avatarRevision.value++
  avatarUnconfirmed.value = false
  await auth.revalidate()
}
async function confirmAvatar() {
  const ticket = auth.capture(); if (!ticket || busy.value) return
  busy.value = true; error.value = ''
  try { await refreshAvatar(ticket) }
  catch (reason) { if (alive && auth.isCurrent(ticket)) error.value = reason instanceof Error ? reason.message : '头像状态确认失败，请重试。' }
  finally { if (alive && auth.isCurrent(ticket)) busy.value = false }
}
function chooseAvatar(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  const ticket = auth.capture()
  if (!file || !ticket || busy.value || avatarUnconfirmed.value) return
  error.value = ''; message.value = ''
  if (file.size > 2097152) { error.value = '图片不能超过 2 MB。'; return }
  if (!/\.(jpe?g|png|webp)$/i.test(file.name)) { error.value = '请选择 JPG、PNG 或 WebP 图片。'; return }
  cropTicket = ticket; cropFile.value = file
}
function cancelCrop() { cropFile.value = undefined; cropTicket = null }
function confirmCrop(file: File) {
  const ticket = cropTicket
  cancelCrop()
  if (ticket && alive && auth.isCurrent(ticket)) void avatar(file)
}
</script>
<template>
  <div class="profile-editor"><form class="profile-form" @submit.prevent="save">
    <p v-if="loading" role="status">正在读取资料…</p>
    <template v-if="baseline">
      <div class="profile-identity"><div class="profile-avatar-edit"><UserAvatar class="profile-avatar" :has-avatar="baseline.has_avatar" :revision="`${baseline.updated_at}:${avatarRevision}`" :alt="baseline.display_name" /><button class="profile-avatar-button" type="button" aria-label="编辑头像" :disabled="busy || avatarUnconfirmed" @click="avatarInput?.click()"><Pencil :size="20" /></button></div>
        <div><div class="profile-name-line"><strong>{{ baseline.display_name }}</strong><span class="badge">{{ auth.user.value?.role === 'admin' ? '管理员' : '普通用户' }}</span></div><p>user_id: {{ baseline.username }}</p></div>
        <input ref="avatarInput" type="file" accept=".jpg,.jpeg,.png,.webp" hidden :disabled="busy || avatarUnconfirmed" @change="chooseAvatar">
        <button v-if="avatarUnconfirmed" class="text-button" type="button" :disabled="busy" @click="confirmAvatar">重新确认头像状态</button>
      </div>
      <section id="profile-basic" class="profile-section"><h2>基本资料</h2><div class="profile-grid">
        <label class="profile-field profile-wide" for="profile-display-name"><span>显示名称 <span class="profile-required">*</span></span><input id="profile-display-name" v-model="draft.display_name" autocomplete="nickname" required :disabled="busy" :aria-invalid="!!fields.display_name"><span v-if="fields.display_name" class="profile-field-error" role="alert">{{ fields.display_name }}</span></label>
        <label class="profile-field" for="profile-gender">性别<select id="profile-gender" v-model="draft.gender" :disabled="busy"><option value="">未填写</option><option value="male">男</option><option value="female">女</option><option value="other">其他</option><option value="undisclosed">不愿透露</option></select></label>
        <label class="profile-field" for="profile-birthday">生日<input id="profile-birthday" v-model="draft.birthday" type="date" :max="birthdayMax" :disabled="busy" :aria-invalid="!!fields.birthday" @focus="birthdayMax = today()"><span v-if="fields.birthday" class="profile-field-error" role="alert">{{ fields.birthday }}</span></label>
        <label class="profile-field profile-wide" for="profile-bio">个性签名<textarea id="profile-bio" v-model="draft.bio" rows="2" placeholder="写一句介绍自己的话" :disabled="busy" :aria-invalid="!!fields.bio"></textarea><span class="profile-field-footer"><span v-if="fields.bio" class="profile-field-error" role="alert">{{ fields.bio }}</span><small>{{ Array.from(draft.bio).length }} / 200</small></span></label>
      </div></section>
      <section id="profile-contact" class="profile-section"><h2>联系方式</h2><div class="profile-grid">
        <label class="profile-field" for="profile-email">邮箱<input id="profile-email" v-model="draft.email" type="email" autocomplete="email" placeholder="name@example.com" :disabled="busy" :aria-invalid="!!fields.email"><span v-if="fields.email" class="profile-field-error" role="alert">{{ fields.email }}</span></label>
        <label class="profile-field" for="profile-phone">手机号<input id="profile-phone" v-model="draft.phone_number" type="tel" autocomplete="tel" placeholder="请输入手机号，支持国家区号" :disabled="busy" :aria-invalid="!!fields.phone_number"><span v-if="fields.phone_number" class="profile-field-error" role="alert">{{ fields.phone_number }}</span></label>
        <label class="profile-field profile-wide" for="profile-address">地址<textarea id="profile-address" v-model="draft.address" rows="2" autocomplete="street-address" placeholder="请输入联系地址" :disabled="busy" :aria-invalid="!!fields.address"></textarea><span v-if="fields.address" class="profile-field-error" role="alert">{{ fields.address }}</span></label>
      </div></section>
    </template>
    <p v-if="error" class="auth-error" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p>
    <button v-if="!baseline && !loading" class="button" type="button" @click="load">重试读取</button>
    <div class="profile-save"><span v-if="busy" class="muted small" role="status">正在保存…</span><button class="button account-primary" :disabled="busy || loading || !dirty">保存</button></div>
    <p class="profile-password"><span>密码与登录安全单独管理</span><RouterLink to="/account/password">修改密码 ↗</RouterLink></p>
  </form>
  <AvatarCropper v-if="cropFile" :file="cropFile" @confirm="confirmCrop" @cancel="cancelCrop" />
  </div>
</template>
