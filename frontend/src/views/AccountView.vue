<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ContactRound, UserRound, UsersRound } from '@lucide/vue'
import ProfileForm from '../features/auth/ProfileForm.vue'
import { useAuth } from '../features/auth/useAuth'
const auth = useAuth(), section = ref('basic')
function select(name: string) { section.value = name; document.getElementById(`profile-${name}`)?.scrollIntoView({ block: 'start' }) }
</script>
<template><section class="account-settings"><nav class="account-settings-nav" aria-label="设置导航"><h2>设置</h2><button type="button" :class="{ selected: section === 'basic' }" :aria-current="section === 'basic' ? 'location' : undefined" @click="select('basic')"><UserRound :size="16" aria-hidden="true" />个人资料</button><button type="button" :class="{ selected: section === 'contact' }" :aria-current="section === 'contact' ? 'location' : undefined" @click="select('contact')"><ContactRound :size="16" aria-hidden="true" />联系方式</button><RouterLink v-if="auth.user.value?.role === 'admin'" to="/admin/users"><UsersRound :size="16" aria-hidden="true" />用户管理</RouterLink></nav><div class="account-settings-content"><h1>个人资料</h1><p class="account-settings-description">设置你的头像和个人信息。管理员可查看这些资料。</p><ProfileForm /></div></section></template>
