<script setup lang="ts">
import { computed, KeepAlive } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ArrowLeft, ArrowUpRight } from '@lucide/vue'
import PlatformBrand from './components/PlatformBrand.vue'

const route = useRoute()
const isConversation = computed(() => route.name === 'agent-conversation')
const isPublic = computed(() => ['agent-home', 'agent-plaza'].includes(String(route.name)))
</script>

<template>
  <div class="app-shell" :class="{ 'conversation-shell': isConversation }">
    <header v-if="!isConversation" class="platform-header" :class="{ 'tool-header': !isPublic }">
      <PlatformBrand />
      <nav v-if="isPublic" class="site-nav" aria-label="网站导航">
        <RouterLink to="/" exact-active-class="active">首页</RouterLink>
        <RouterLink to="/agents" active-class="active">智能体</RouterLink>
      </nav>
      <RouterLink v-else class="back-link" to="/agents">
        <ArrowLeft :size="16" aria-hidden="true" />智能体目录
      </RouterLink>
      <RouterLink v-if="isPublic" class="button header-cta" :class="{ 'button-primary': route.name === 'agent-home' }" to="/agents">
        探索智能体 <ArrowUpRight :size="17" aria-hidden="true" />
      </RouterLink>
      <span v-else class="badge">独立工作空间</span>
    </header>

    <main class="main-content">
      <RouterView v-slot="{ Component }">
        <KeepAlive include="AgentConversationView">
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>

    <footer v-if="isPublic" class="site-footer">
      <PlatformBrand />
      <p>让每一项工作，找到合适的智能体。</p>
      <RouterLink to="/agents">探索智能体 <ArrowUpRight :size="15" aria-hidden="true" /></RouterLink>
    </footer>
  </div>
</template>
