<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { CircleQuestionMark, Network, ShieldCheck, Square } from '@lucide/vue'
import { ApiError } from '../api/client'
import { submitReview } from '../api/reviews'
import ExecutionStatus from '../components/workbench/ExecutionStatus.vue'
import ReviewReport from '../features/institution-review/ReviewReport.vue'
import ReviewUpload from '../features/institution-review/ReviewUpload.vue'
import type { ReviewSource, ReviewStatus, ReviewSubmission } from '../features/institution-review/types'

const route = useRoute()
const agentId = computed(() => String(route.params.agentId ?? ''))
const isKnownAgent = computed(() => agentId.value === 'institution-review')
const status = ref<ReviewStatus>('idle')
const statusMessage = ref('')
const report = ref('')
const source = ref<ReviewSource>()
const stopped = ref(false)
const stopDialog = ref<HTMLDialogElement>()
let controller: AbortController | null = null
function reset() {
  controller?.abort(); controller = null
  status.value = 'idle'; statusMessage.value = ''; report.value = ''; stopped.value = false
}
watch(agentId, reset)
onBeforeUnmount(() => { controller?.abort(); stopDialog.value?.close() })
async function runReview(submission: ReviewSubmission) {
  if (status.value === 'submitting') return
  const request = new AbortController()
  controller = request
  status.value = 'submitting'; stopped.value = false
  statusMessage.value = '正在核对条款与相关依据，完成后会显示完整报告。'
  report.value = ''
  source.value = { draft: submission.file.name, mode: submission.mode,
    ...(submission.mode === 'standard_document' ? { standard: submission.standardFile.name } : {}) }
  try {
    const markdown = await submitReview(submission, request.signal)
    if (request.signal.aborted || controller !== request) return
    report.value = markdown
    status.value = 'success'; statusMessage.value = '审核完成'
  } catch (error) {
    if (request.signal.aborted || controller !== request) return
    status.value = 'error'
    statusMessage.value = error instanceof ApiError ? error.message : '审核未能完成，请稍后重试。'
  } finally {
    if (controller === request) { controller = null; stopDialog.value?.close() }
  }
}
function stopWaiting() {
  if (status.value !== 'submitting') { stopDialog.value?.close(); return }
  controller?.abort(); controller = null
  status.value = 'idle'; stopped.value = true
  stopDialog.value?.close()
}
function revise() { report.value = ''; status.value = 'idle'; statusMessage.value = '' }
</script>

<template>
  <section v-if="!isKnownAgent" class="not-found-panel">
    <CircleQuestionMark :size="42" aria-hidden="true" /><h1>暂时找不到这位智能体</h1><p>回到目录，看看当前的智能体。</p><RouterLink class="button button-primary" to="/agents">返回智能体目录</RouterLink>
  </section>
  <section v-else class="workbench-page">
    <template v-if="!report">
      <div class="page-title"><div><div class="eyebrow"><ShieldCheck :size="20" aria-hidden="true" />制度审核</div><h1>从一份草稿，开始审核。</h1><p>选择审核依据，材料准备好后再开始。</p></div><RouterLink class="button" :to="`/agents/${agentId}/flow`"><Network :size="18" aria-hidden="true" />查看审核流程</RouterLink></div>
    </template>
    <ReviewUpload v-show="!report" :disabled="status === 'submitting'" @submit="runReview" />
    <div v-if="status === 'submitting'" class="review-waiting">
      <ExecutionStatus :status="status" :message="statusMessage" />
      <div class="row between"><span class="muted small">停止等待不会撤回已提交的审核。</span><button class="button button-danger" type="button" @click="stopDialog?.showModal()"><Square :size="16" aria-hidden="true" />停止等待</button></div>
    </div>
    <ExecutionStatus v-else-if="status === 'error'" :status="status" :message="statusMessage" />
    <p v-if="stopped" class="inline-note" role="status">已停止等待。材料仍在当前页面，已提交的审核可能继续执行；重新提交会从头开始。</p>
    <ReviewReport v-if="report" :markdown="report" :source="source" @restart="revise" />
    <dialog ref="stopDialog" class="confirm-dialog" aria-labelledby="stop-title"><h2 id="stop-title">停止等待报告？</h2><p>停止等待不会撤回已提交的审核。若重新提交，将从头开始。</p><div class="dialog-actions"><button class="button" type="button" @click="stopDialog?.close()">继续等待</button><button class="button button-danger" type="button" @click="stopWaiting">停止等待</button></div></dialog>
  </section>
</template>
