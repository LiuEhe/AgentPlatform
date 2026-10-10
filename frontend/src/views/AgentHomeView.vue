<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="landing-page">
    <section class="landing-hero">
      <div class="landing-copy">
        <div class="eyebrow"><span class="eyebrow-line"></span> INTELLIGENCE, AT WORK</div>
        <h1 class="landing-title">让AI<br /><span>走入工作</span></h1>
        <p class="landing-description">
          一个面向真实任务的智能体平台，把专业能力组织成清晰的流程。
        </p>
        <RouterLink class="landing-cta" to="/agents">
          <span>进入智能体广场</span>
          <span class="landing-cta-arrow" aria-hidden="true">↗</span>
        </RouterLink>
        <div class="landing-caption"><span class="caption-rule"></span> 发挥你的创意 </div>
      </div>

      <div class="agent-word-art" role="img" aria-label="Agent platform">
        <span class="word-art-orbit word-art-orbit-wide" aria-hidden="true"></span>
        <span class="word-art-orbit word-art-orbit-small" aria-hidden="true"></span>
        <span class="word-art-spark" aria-hidden="true">✳</span>
        <span class="word-art-label">AGENT / PLATFORM</span>
        <span class="word-art-name" aria-hidden="true">Agent</span>
        <span class="word-art-baseline"><i></i> INTELLIGENCE, AT WORK</span>
      </div>

      <div class="landing-index"><span>01</span><span class="index-divider"></span><span>PLATFORM</span></div>
    </section>

    <section class="landing-principles" aria-label="平台特点">
      <div class="principle-intro">
        <span class="principle-kicker">A CLEARER WAY TO WORK</span>
        <p>能力不止于回答，<br />更在于把事情做好。</p>
      </div>
      <div class="principle-item">
        <span class="principle-glyph">↗</span>
        <div><strong>从任务出发</strong><span>为具体工作找到合适的智能体</span></div>
      </div>
      <div class="principle-item">
        <span class="principle-glyph">⌁</span>
        <div><strong>让过程清楚</strong><span>沿着明确的步骤处理复杂事项</span></div>
      </div>
      <div class="principle-item">
        <span class="principle-glyph">⌗</span>
        <div><strong>交付可读结果</strong><span>把分析整理成便于使用的成果</span></div>
      </div>
    </section>

  </div>
</template>
