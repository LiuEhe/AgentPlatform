<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ArrowUpRight, CircleQuestionMark, MessagesSquare, PanelsTopLeft, ShieldCheck } from '@lucide/vue'

const agents = [
  { name: '会话助手', to: '/agents/conversation-assistant', icon: MessagesSquare, kind: '对话型', description: '讨论问题、起草文字、整理材料。围绕上下文连续交流，让思路逐渐清楚。', tags: ['多轮对话', '文件讨论', '写作整理'] },
  { name: '制度审核', to: '/agents/institution-review', icon: ShieldCheck, kind: '任务型', description: '上传制度草稿，选择标准或知识库。查看条款问题、相关依据与完整报告。', tags: ['制度对照', '术语检查', '报告导出'] },
]
</script>

<template>
  <section class="agent-directory">
    <div class="directory-heading">
      <div class="eyebrow"><PanelsTopLeft :size="20" aria-hidden="true" />智能体目录</div>
      <h1>找到适合这件事的智能体。</h1>
      <p>每个智能体都有自己的工作空间，选好后即可进入。</p>
    </div>
    <div class="directory-label"><span>全部智能体</span><span class="muted">{{ agents.length }} 个智能体</span></div>
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
