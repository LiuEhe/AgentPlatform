<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { ApiError } from '../../api/client'
import { exportReviewToWord } from '../../api/reviews'

const props = defineProps<{ markdown: string }>()
const isDownloading = ref(false)
const downloadError = ref('')
let downloadController: AbortController | undefined

watch(() => props.markdown, () => {
  downloadController?.abort()
  downloadController = undefined
  isDownloading.value = false
  downloadError.value = ''
})

onBeforeUnmount(() => downloadController?.abort())

async function downloadWord() {
  if (isDownloading.value || !props.markdown.trim()) return
  const controller = new AbortController()
  downloadController = controller
  isDownloading.value = true
  downloadError.value = ''
  try {
    const blob = await exportReviewToWord(props.markdown, controller.signal)
    if (controller.signal.aborted) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '制度审核报告.docx'
    try {
      document.body.append(link)
      link.click()
    } finally {
      link.remove()
      // 留出浏览器开始读取附件的时间，再释放临时 URL。
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      downloadError.value = error instanceof ApiError
        ? error.message
        : 'Word 文件下载失败，请稍后重试。'
    }
  } finally {
    if (downloadController === controller) {
      downloadController = undefined
      isDownloading.value = false
    }
  }
}

const safeHtml = computed(() => {
  const html = marked.parse(props.markdown, { async: false })
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
  })
})
</script>

<template>
  <section class="report-panel" aria-labelledby="report-title">
    <div class="report-heading">
      <div>
        <div class="eyebrow"><span class="eyebrow-line"></span> REVIEW REPORT</div>
        <h2 id="report-title">审核结果</h2>
      </div>
      <div class="report-actions">
        <span class="report-ready"><span class="report-ready-dot"></span> 已生成</span>
        <button
          type="button"
          class="button button-quiet report-download"
          :disabled="isDownloading || !markdown.trim()"
          :aria-busy="isDownloading"
          @click="downloadWord"
        >
          <span aria-hidden="true">↓</span>
          {{ isDownloading ? '正在生成…' : '下载 Word' }}
        </button>
      </div>
    </div>
    <p v-if="downloadError" class="field-error" role="alert">{{ downloadError }}</p>
    <div class="markdown-content" v-html="safeHtml"></div>
  </section>
</template>
