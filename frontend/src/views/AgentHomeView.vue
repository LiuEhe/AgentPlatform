<script setup lang="ts">
import { RouterLink } from 'vue-router'

const agents = [
  {
    id: 'institution-review',
    title: '制度审核助手',
    category: '文档审核',
    description: '审查制度草稿中的条款冲突、重复内容与术语使用，生成清晰的修改建议。',
    capabilities: ['DOCX 文档', '条款冲突检查', '修改建议'],
    icon: 'review',
    accent: 'violet',
    availability: '可使用',
  },
]
</script>

<template>
  <div class="home-page">
    <section class="home-hero">
      <div class="hero-copy">
        <div class="eyebrow"><span class="eyebrow-line"></span> AGENT WORKSPACE</div>
        <h1>让每一个<br /><span>工作流，都有智能。</span></h1>
        <p class="hero-description">
          选择一个智能体，从熟悉的工作开始。让专业能力在清晰、可靠的流程中落地。
        </p>
        <a class="hero-scroll" href="#agent-list">
          <span class="scroll-icon">↓</span> 探索可用智能体
        </a>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="art-orbit art-orbit-outer"></div>
        <div class="art-orbit art-orbit-inner"></div>
        <div class="art-star star-one">✳</div>
        <div class="art-star star-two">✦</div>
        <div class="art-core">
          <span class="core-glow"></span>
          <svg viewBox="0 0 100 100" fill="none">
            <path d="M50 13 82 31v38L50 87 18 69V31L50 13Z" />
            <path d="m37 57 13-23 13 23M41 49h18M40 66h20" />
          </svg>
        </div>
        <div class="art-label label-top"><span class="label-pip"></span> 智能理解</div>
        <div class="art-label label-bottom"><span class="label-pip"></span> 流程执行</div>
        <div class="art-caption">能力 · 流程 · 结果</div>
      </div>
      <div class="hero-index"><span>01</span> / 01</div>
    </section>

    <section id="agent-list" class="agent-section">
      <div class="section-heading">
        <div>
          <div class="eyebrow"><span class="eyebrow-line"></span> YOUR TOOLKIT</div>
          <h2>智能体<span class="heading-period">.</span></h2>
        </div>
        <div class="section-count"><span class="count-number">{{ agents.length.toString().padStart(2, '0') }}</span> 个可用</div>
      </div>

      <div class="agent-grid">
        <article v-for="agent in agents" :key="agent.id" class="agent-card">
          <div class="card-topline">
            <span class="agent-category"><span class="category-mark">✳</span>{{ agent.category }}</span>
            <span class="availability"><span class="availability-dot"></span>{{ agent.availability }}</span>
          </div>

          <div class="agent-card-body">
            <div class="agent-icon" :class="`agent-icon-${agent.accent}`" aria-hidden="true">
              <svg v-if="agent.icon === 'review'" viewBox="0 0 48 48" fill="none">
                <path d="M14 6.5h13l8 8V39a2.5 2.5 0 0 1-2.5 2.5h-18A2.5 2.5 0 0 1 12 39V9a2.5 2.5 0 0 1 2-2.5Z" />
                <path d="M27 7v9h8M18 23h11M18 29h11M18 35h7" />
                <path d="m29 31 3 3 6-7" />
              </svg>
            </div>
            <div class="agent-card-copy">
              <h3>{{ agent.title }}</h3>
              <p>{{ agent.description }}</p>
            </div>
          </div>

          <div class="agent-capabilities">
            <span v-for="capability in agent.capabilities" :key="capability" class="capability-tag">
              {{ capability }}
            </span>
          </div>

          <RouterLink class="agent-open" :to="`/agents/${agent.id}`">
            <span>打开智能体</span>
            <span class="open-arrow" aria-hidden="true">↗</span>
          </RouterLink>
        </article>

        <div class="coming-card" aria-label="更多智能体即将推出">
          <div class="coming-mark">＋</div>
          <span>更多智能体</span>
          <span class="coming-note">正在准备中</span>
        </div>
      </div>
    </section>

    <section class="home-note">
      <span class="note-mark">✳</span>
      <p>每一位智能体，都为一件具体的事而来。</p>
      <span class="note-caption">BUILT FOR REAL WORK</span>
    </section>
  </div>
</template>
