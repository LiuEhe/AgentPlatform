<script setup lang="ts">
import { RouterLink } from 'vue-router'

const agents = [
  {
    id: 'institution-review',
    name: '制度审核助手',
    category: '文档审核',
    description: '审查制度草稿中的条款冲突、重复内容与术语使用，生成清晰的审核报告与修改建议。',
    capabilities: ['DOCX 文档', '条款冲突检查', '术语检查', '修改建议'],
  },
]
</script>

<template>
  <div class="plaza-page">
    <div class="plaza-breadcrumb"><RouterLink to="/">首页</RouterLink><span>/</span><span>智能体广场</span></div>

    <section class="plaza-heading">
      <div class="plaza-heading-copy">
        <div class="eyebrow"><span class="eyebrow-line"></span> THE AGENT DIRECTORY</div>
        <h1>智能体创意<br /><span>广场</span></h1>
        <p>每个智能体，都围绕一类具体任务设计。选择一个开始，让繁琐的工作变得更清晰。</p>
      </div>
      <div class="plaza-heading-aside" aria-hidden="true">
        <span class="plaza-aside-orbit plaza-orbit-one"></span>
        <span class="plaza-aside-orbit plaza-orbit-two"></span>
        <span class="plaza-aside-core">A</span>
        <span class="plaza-aside-label">CAPABILITY<br />COLLECTION</span>
      </div>
    </section>

    <section class="plaza-catalog" aria-labelledby="catalog-title">
      <div class="catalog-heading">
        <div>
          <div class="eyebrow"><span class="eyebrow-line"></span> AVAILABLE NOW</div>
          <h2 id="catalog-title">可用智能体<span class="heading-period">.</span></h2>
        </div>
        <div class="catalog-count"><span>0{{ agents.length }}</span> 个已上线</div>
      </div>

      <div class="plaza-grid">
        <RouterLink
          v-for="agent in agents"
          :key="agent.id"
          class="plaza-agent-card"
          :to="`/agents/${agent.id}`"
        >
          <div class="plaza-card-visual">
            <div class="plaza-card-topline">
              <span class="plaza-category"><span class="category-mark">✳</span>{{ agent.category }}</span>
              <span class="plaza-availability"><span class="availability-dot"></span>可使用</span>
            </div>
            <div class="document-art" aria-hidden="true">
              <div class="document-shadow"></div>
              <div class="document-sheet">
                <span class="document-label">POLICY / REVIEW</span>
                <span class="document-line line-long"></span>
                <span class="document-line line-mid"></span>
                <span class="document-line line-short"></span>
                <span class="document-highlight"><span>§</span> 条款一致性检查</span>
                <span class="document-line line-mid"></span>
                <span class="document-line line-long"></span>
                <span class="document-check">✓</span>
              </div>
              <span class="document-orbit orbit-left"></span>
              <span class="document-orbit orbit-right"></span>
              <span class="document-spark">✳</span>
            </div>
            <span class="plaza-card-index">AGENT / 001</span>
          </div>

          <div class="plaza-card-content">
            <h3>{{ agent.name }}<span aria-hidden="true">↗</span></h3>
            <p>{{ agent.description }}</p>
            <div class="plaza-capabilities">
              <span v-for="capability in agent.capabilities" :key="capability">{{ capability }}</span>
            </div>
            <div class="plaza-card-footer">
              <span>进入工作台</span>
              <span class="plaza-card-arrow" aria-hidden="true">→</span>
            </div>
          </div>
        </RouterLink>

        <article class="plaza-coming-card">
          <div class="coming-orbit" aria-hidden="true"><span>+</span><i></i><b></b></div>
          <span class="coming-kicker">MORE CAPABILITIES</span>
          <h3>新的智能体<br />正在加入。</h3>
          <p>我们正在把更多专业流程，变成随时可用的能力。</p>
          <span class="coming-status"><span></span> 持续构建中</span>
        </article>
      </div>
    </section>

    <section class="plaza-bottom-note">
      <span class="note-mark">✳</span>
      <p>先从一项具体工作开始，再把能力带到更多地方。</p>
      <RouterLink to="/">回到首页 <span aria-hidden="true">↗</span></RouterLink>
    </section>
  </div>
</template>
