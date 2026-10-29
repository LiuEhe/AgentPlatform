<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ArrowRight, ArrowUp, ArrowUpRight, BookOpen, FileText, MessagesSquare, PanelsTopLeft, ShieldCheck } from '@lucide/vue'

const values = [
  { icon: MessagesSquare, title: '先聊清楚，再往前走', description: '一个问题、一段文字，都能成为开始。会话助手与你持续交流，把模糊的想法说具体。' },
  { icon: FileText, title: '让材料留在讨论里', description: '文件与消息放在一起，提问与上下文相邻，让每次补充都能接得上。' },
  { icon: ShieldCheck, title: '把专业任务交给专业智能体', description: '制度审核拥有独立的材料、依据与报告界面，让每一步都有清晰的目的。' },
]

function showDetails() {
  document.getElementById('platform-details')?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
  })
}
</script>

<template>
  <div class="landing-page">
    <section class="landing-hero">
      <div class="hero-copy">
        <div class="eyebrow"><span class="eyebrow-rule"></span>为日常工作，打开更多可能</div>
        <h1>把日常工作，<br />交给合适的<span>智能体。</span></h1>
        <p>从一个问题，到一份有依据的审核报告。<br />让对话、材料与结果，在同一个平台有序展开。</p>
        <div class="hero-actions">
          <RouterLink class="button button-primary" to="/agents">探索智能体 <ArrowUpRight :size="18" aria-hidden="true" /></RouterLink>
          <button class="text-button" type="button" @click="showDetails">了解 AgentPlatform <ArrowRight :size="17" aria-hidden="true" /></button>
        </div>
        <div class="hero-caption"><span>自然对话</span><span>材料理解</span><span>专业审核</span></div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="art-orbit"></div>
        <div class="art-small-note">从想法，走向结果。<span>YOUR EVERYDAY WORKSPACE</span></div>
        <div class="art-sheet sheet-back">
          <div class="art-sheet-label"><ShieldCheck :size="20" />制度审核</div>
          <div class="art-line long"></div><div class="art-line"></div><div class="art-line short"></div>
          <div class="art-proof"><BookOpen :size="17" />让结论，有据可循。</div>
        </div>
        <div class="art-sheet sheet-front">
          <div class="art-sheet-label"><MessagesSquare :size="20" />会话助手</div>
          <div class="art-question">“想法有点多，<br />一起理一理？”</div>
          <div class="art-answer">当然。我们从最重要的事开始。</div>
          <div class="art-compose"><span>从一个问题开始…</span><ArrowUp :size="22" /></div>
        </div>
        <div class="art-tag"><PanelsTopLeft :size="16" />合适的助手，清晰的工作。</div>
      </div>
    </section>
    <section id="platform-details" class="landing-values">
      <span class="section-kicker">更自然地开始，更清楚地完成</span>
      <h2>让工具，顺着你的工作方式。</h2>
      <div class="value-grid">
        <article v-for="value in values" :key="value.title">
          <component :is="value.icon" :size="25" :stroke-width="1.75" aria-hidden="true" />
          <h3>{{ value.title }}</h3><p>{{ value.description }}</p>
        </article>
      </div>
    </section>
    <section class="landing-invitation">
      <div><span class="section-kicker">开始使用 AGENTPLATFORM</span><h2>下一件事，交给谁一起完成？</h2><p>到智能体目录里，找到适合当前任务的伙伴。</p></div>
      <RouterLink class="button button-primary" to="/agents">浏览智能体 <ArrowUpRight :size="18" aria-hidden="true" /></RouterLink>
    </section>
  </div>
</template>
