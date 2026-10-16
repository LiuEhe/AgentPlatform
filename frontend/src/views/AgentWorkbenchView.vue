<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '../api/client'
import { submitReview } from '../api/reviews'
import ExecutionStatus from '../components/workbench/ExecutionStatus.vue'
import ReviewReport from '../features/institution-review/ReviewReport.vue'
import ReviewUpload from '../features/institution-review/ReviewUpload.vue'
import type { ReviewStatus, ReviewSubmission } from '../features/institution-review/types'

const route = useRoute()
const agentId = computed(() => String(route.params.agentId ?? ''))
const isKnownAgent = computed(() => agentId.value === 'institution-review')
const status = ref<ReviewStatus>('idle')
const statusMessage = ref('')
const report = ref('')

watch(agentId, () => {
  status.value = 'idle'
  statusMessage.value = ''
  report.value = ''
})

async function runReview(submission: ReviewSubmission) {
  if (status.value === 'submitting') return
  status.value = 'submitting'
  statusMessage.value = '正在审阅文档中的条款与术语…'
  report.value = ''

  try {
    report.value = await submitReview(submission)
    status.value = 'success'
    statusMessage.value = '审核完成，报告已准备好。'
  } catch (error) {
    status.value = 'error'
    statusMessage.value = error instanceof ApiError
      ? error.message
      : '审核未能完成，请稍后重试。'
  }
}
</script>

<template>
  <div v-if="!isKnownAgent" class="not-found-panel">
    <span class="not-found-mark" aria-hidden="true">?</span>
    <div class="eyebrow"><span class="eyebrow-line"></span> AGENT NOT FOUND</div>
    <h1>暂时找不到这位智能体</h1>
    <p>这个入口可能已调整，回到智能体主页看看当前可用的能力。</p>
    <RouterLink class="button button-primary" to="/">
      返回智能体主页 <span class="button-arrow" aria-hidden="true">↗</span>
    </RouterLink>
  </div>

  <div v-else class="workbench-page">
    <div class="breadcrumb">
      <RouterLink to="/agents">智能体广场</RouterLink>
      <span aria-hidden="true">/</span>
      <span>制度审核助手</span>
    </div>

    <section class="workbench-intro">
      <div class="workbench-title-wrap">
        <div class="workbench-agent-icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none">
            <path d="M14 6.5h13l8 8V39a2.5 2.5 0 0 1-2.5 2.5h-18A2.5 2.5 0 0 1 12 39V9a2.5 2.5 0 0 1 2-2.5Z" />
            <path d="M27 7v9h8M18 23h11M18 29h11M18 35h7" />
            <path d="m29 31 3 3 6-7" />
          </svg>
        </div>
        <div>
          <div class="eyebrow"><span class="eyebrow-line"></span> DOCUMENT INTELLIGENCE</div>
          <h1>制度审核助手<span class="heading-period">.</span></h1>
          <p>读懂每一条制度要求，帮你发现冲突、重复与值得斟酌的表达。</p>
        </div>
      </div>
      <div class="workbench-tags">
        <span class="workbench-tag"><span class="tag-dot"></span> 文档审核</span>
        <span class="workbench-tag">DOCX</span>
        <RouterLink class="workbench-tag flow-link" :to="`/agents/${agentId}/flow`">查看流程图 <span aria-hidden="true">↗</span></RouterLink>
      </div>
    </section>

    <div class="workbench-layout">
      <div class="workbench-main-column">
        <ReviewUpload :disabled="status === 'submitting'" @submit="runReview" />
        <ExecutionStatus :status="status" :message="statusMessage" />
        <ReviewReport v-if="report" :markdown="report" />
      </div>

      <aside class="workbench-aside">
        <section class="aside-card about-card">
          <div class="aside-card-kicker">ABOUT THIS AGENT</div>
          <h2>审核更清晰，<br />修订更有据。</h2>
          <p>选择制度知识库或上传标准文档作为依据，逐条审阅草稿，并整理需要关注的问题与建议。</p>
          <div class="aside-divider"></div>
          <div class="aside-fact"><span class="fact-index">01</span><span>DOCX 文档输入</span></div>
          <div class="aside-fact"><span class="fact-index">02</span><span>术语与条款检查</span></div>
          <div class="aside-fact"><span class="fact-index">03</span><span>Markdown 审核报告</span></div>
        </section>

        <section class="aside-tip">
          <span class="tip-icon" aria-hidden="true">✳</span>
          <div>
            <strong>小提示</strong>
            <p>上传前请确认文档已保存为 `.docx` 格式，清晰完整的制度文本能帮助获得更准确的审核结果。</p>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
