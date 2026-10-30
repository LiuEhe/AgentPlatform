<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { computed, onMounted, ref } from 'vue'
import { ArrowUpRight, CircleQuestionMark, MessagesSquare, PanelsTopLeft, ShieldCheck } from '@lucide/vue'
import { listAgents } from '../api/agents'
import type { AgentMetadata } from '../api/agents'

const entries = {
  conversation_assistant: { to: '/agents/conversation-assistant', icon: MessagesSquare, kind: '对话型', tags: ['多轮对话', '文件讨论', '写作整理'] },
  institution_review: { to: '/agents/institution-review', icon: ShieldCheck, kind: '任务型', tags: ['制度对照', '术语检查', '报告导出'] },
}
const metadata = ref<AgentMetadata[]>([])
const loading = ref(true)
const error = ref('')
const agents = computed(() => metadata.value.flatMap(agent => {
  const entry = entries[agent.agent_id as keyof typeof entries]
  return entry ? [{ ...agent, ...entry }] : []
}))
async function load() {
  loading.value = true
  error.value = ''
  try { metadata.value = await listAgents() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '智能体目录加载失败。' }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section class="agent-directory">
    <div class="directory-heading">
      <div class="eyebrow"><PanelsTopLeft :size="20" aria-hidden="true" />智能体目录</div>
      <h1>找到适合这件事的智能体。</h1>
      <p>每个智能体都有自己的工作空间，选好后即可进入。</p>
    </div>
    <div class="directory-label"><span>全部智能体</span><span class="muted">{{ agents.length }} 个智能体</span></div>
    <p v-if="loading" role="status">正在加载智能体…</p>
    <p v-if="error" role="alert">{{ error }} <button class="text-button" type="button" @click="load">重试</button></p>
    <div class="agent-grid">
      <RouterLink v-for="agent in agents" :key="agent.to" class="agent-card" :to="agent.to">
        <div class="agent-symbol"><component :is="agent.icon" :size="28" :stroke-width="1.75" aria-hidden="true" /></div>
        <div class="row between"><h2>{{ agent.name }}</h2><span class="badge">{{ agent.kind }}</span></div>
        <p>{{ agent.description }}</p>
        <div class="agent-tags"><span v-for="tag in agent.tags" :key="tag">{{ tag }}</span></div>
        <span class="agent-entry">进入{{ agent.name }} <ArrowUpRight :size="18" aria-hidden="true" /></span>
      </RouterLink>
    </div>
    <div class="directory-foot"><span><CircleQuestionMark :size="16" aria-hidden="true" />选好智能体后，将进入对应的独立页面。</span><RouterLink to="/">了解 AgentPlatform <ArrowUpRight :size="15" aria-hidden="true" /></RouterLink></div>
  </section>
</template>
