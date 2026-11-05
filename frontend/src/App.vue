<script setup lang="ts">
import { computed, KeepAlive } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ArrowLeft, ArrowUpRight } from '@lucide/vue'
import PlatformBrand from './components/PlatformBrand.vue'
import AccountMenu from './features/auth/AccountMenu.vue'
import { useAuth } from './features/auth/useAuth'

const route = useRoute()
const auth = useAuth()
const isAuthPage = computed(() => ['login', 'register'].includes(String(route.name)))
const identityReady = computed(() => ['authenticated', 'password-required'].includes(auth.phase.value))
const privateAllowed = computed(() => !route.meta.private || (identityReady.value &&
  (auth.phase.value !== 'password-required' || route.name === 'password') &&
  (!route.meta.admin || auth.user.value?.role === 'admin')))
const isConversation = computed(() => route.name === 'agent-conversation')
const isPublic = computed(() => ['agent-home', 'agent-plaza'].includes(String(route.name)))
</script>

<template>
  <div class="app-shell" :class="{ 'conversation-shell': isConversation }">
    <header v-if="!isConversation" class="platform-header" :class="{ 'tool-header': !isPublic && !isAuthPage }">
      <PlatformBrand />
      <nav v-if="isPublic && !isAuthPage" class="site-nav" aria-label="网站导航">
        <RouterLink to="/" exact-active-class="active">首页</RouterLink>
        <RouterLink to="/agents" active-class="active">智能体</RouterLink>
      </nav>
      <RouterLink v-else-if="!isAuthPage" class="back-link" to="/agents">
        <ArrowLeft :size="16" aria-hidden="true" />智能体目录
      </RouterLink>
      <AccountMenu v-if="!isAuthPage && (identityReady || auth.phase.value === 'anonymous')" />
      <span v-if="!isPublic && !isAuthPage" class="badge">独立工作空间</span>
    </header>

    <main class="main-content">
      <RouterView v-slot="{ Component }">
        <div v-if="auth.user.value" :key="auth.epoch.value" v-show="route.meta.private && privateAllowed" :inert="!route.meta.private || !privateAllowed" class="route-content private-content">
          <KeepAlive include="AgentConversationView"><component :is="Component" v-if="route.meta.private" /></KeepAlive>
        </div>
        <component :is="Component" v-if="!route.meta.private" />
        <section v-if="route.meta.private && !privateAllowed" class="auth-profile" role="status"><h1>正在确认登录状态</h1><p>确认后即可继续工作。</p><button class="button" @click="auth.revalidate()">重新确认</button><RouterLink to="/login" class="text-button">前往登录</RouterLink></section>
      </RouterView>
    </main>

    <footer v-if="isAuthPage" class="auth-support"><div><b>01</b><strong>井然有序</strong><p>让想法与材料，有自己的位置。</p></div><div><b>02</b><strong>连贯自然</strong><p>保留思考的脉络，接续每一次工作。</p></div><div><b>03</b><strong>灵活开放</strong><p>按需选择能力，适应不同的工作方式。</p></div><small>AgentPlatform</small></footer>
    <p v-if="!auth.storageAvailable.value" class="auth-storage-note" role="status">浏览器存储不可用，退出后请关闭其他已打开的平台标签页。</p>
    <div v-if="auth.phase.value === 'logout-pending'" class="auth-profile" role="alert"><p>退出结果尚未确认，私有内容已清除。请重试退出，或重新输入账号密码登录。</p><button class="button" @click="auth.logout()">重试退出</button></div>

    <footer v-if="isPublic" class="site-footer">
      <PlatformBrand />
      <p>让每一项工作，找到合适的智能体。</p>
      <RouterLink to="/agents">探索智能体 <ArrowUpRight :size="15" aria-hidden="true" /></RouterLink>
    </footer>
  </div>
</template>
