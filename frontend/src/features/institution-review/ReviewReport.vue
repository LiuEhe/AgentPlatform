<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowLeft, CircleCheck, Copy, Download, FileText, LoaderCircle } from '@lucide/vue'
import DOMPurify from 'dompurify'
import { Marked } from 'marked'
import { ApiError } from '../../api/client'
import { exportReviewToWord } from '../../api/reviews'
import type { ReviewSource } from './types'

const props = defineProps<{ markdown: string; source?: ReviewSource }>()
const emit = defineEmits<{ restart: [] }>()
const isDownloading = ref(false)
const downloadError = ref('')
const copyState = ref<'idle' | 'copied' | 'manual'>('idle')
const activeHeading = ref('')
const paper = ref<HTMLElement>()
let downloadController: AbortController | undefined
watch(() => props.markdown, () => {
  downloadController?.abort(); downloadController = undefined
  isDownloading.value = false; downloadError.value = ''; copyState.value = 'idle'; activeHeading.value = ''
})
onBeforeUnmount(() => downloadController?.abort())

const rendered = computed(() => {
  let sequence = 0
  const headings: { id: string; label: string }[] = []
  const parser = new Marked({
    renderer: {
      heading({ tokens, depth }) {
        const id = 'review-heading-' + (++sequence)
        const inline = this.parser.parseInline(tokens)
        if (depth <= 2) {
          const label = document.createElement('span')
          label.innerHTML = DOMPurify.sanitize(inline)
          headings.push({ id, label: label.textContent || '报告章节' })
        }
        return `<h${depth} id="${id}">${inline}</h${depth}>\n`
      },
    },
  })
  const html = parser.parse(props.markdown, { async: false })
  return { html: DOMPurify.sanitize(html, { USE_PROFILES: { html: true } }), headings }
})
function goTo(id: string) {
  activeHeading.value = id
  paper.value?.querySelector('#' + id)?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start',
  })
}
async function copyReport() {
  try { await navigator.clipboard.writeText(props.markdown); copyState.value = 'copied' }
  catch { copyState.value = 'manual' }
}
async function downloadWord() {
  if (isDownloading.value || !props.markdown.trim()) return
  const controller = new AbortController()
  downloadController = controller; isDownloading.value = true; downloadError.value = ''
  try {
    const blob = await exportReviewToWord(props.markdown, controller.signal)
    if (controller.signal.aborted) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = '制度审核报告.docx'
    try { document.body.append(link); link.click() }
    finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000) }
  } catch (error) {
    if (!controller.signal.aborted) downloadError.value = error instanceof ApiError ? error.message : 'Word 文件下载失败，请稍后重试。'
  } finally {
    if (downloadController === controller) { downloadController = undefined; isDownloading.value = false }
  }
}
</script>

<template>
  <section class="report-panel" aria-labelledby="report-title">
    <div class="report-toolbar">
      <div class="row"><span class="badge badge-success"><CircleCheck :size="15" aria-hidden="true" />审核完成</span><span v-if="source" class="report-document-name">{{ source.draft }}</span></div>
      <div class="report-actions">
        <button class="button" type="button" @click="copyReport"><Copy :size="17" aria-hidden="true" />{{ copyState === 'copied' ? '已复制' : '复制报告' }}</button>
        <button class="button button-primary" type="button" :disabled="isDownloading || !markdown.trim()" :aria-busy="isDownloading" @click="downloadWord">
          <LoaderCircle v-if="isDownloading" class="spin" :size="17" aria-hidden="true" /><Download v-else :size="17" aria-hidden="true" />{{ isDownloading ? '正在生成…' : '下载 Word' }}
        </button>
      </div>
    </div>
    <p v-if="copyState === 'copied'" class="visually-hidden" role="status">完整报告已复制。</p>
    <div v-if="copyState === 'manual'" class="copy-fallback"><label for="report-copy">无法自动复制，请选择以下完整原文手动复制。</label><textarea id="report-copy" :value="markdown" readonly @focus="($event.target as HTMLTextAreaElement).select()"></textarea></div>
    <p v-if="downloadError" class="field-error" role="alert">{{ downloadError }} 报告已保留，可以单独重试下载。</p>
    <div class="report-layout" :class="{ 'report-without-source': !source }">
      <nav class="report-toc" aria-label="报告目录"><span class="section-kicker">报告目录</span>
        <a v-for="heading in rendered.headings" :key="heading.id" :href="'#' + heading.id" :class="{ active: (activeHeading || rendered.headings[0]?.id) === heading.id }" @click.prevent="goTo(heading.id)">{{ heading.label }}</a>
        <button class="text-button" type="button" @click="emit('restart')"><ArrowLeft :size="16" aria-hidden="true" />重新审核</button>
      </nav>
      <article ref="paper" class="report-paper">
        <div class="paper-kicker">制度审核报告</div><h1 id="report-title">审核报告</h1>
        <p v-if="source" class="report-meta">{{ source.draft }}<br />审核方式：{{ source.mode === 'standard_document' ? '标准文档对照' : '知识库审核' }}</p>
        <div class="markdown-content" v-html="rendered.html"></div>
      </article>
      <aside v-if="source" class="report-source">
        <div class="summary-card"><h2>本次材料</h2>
          <div class="source-file"><span><FileText :size="16" aria-hidden="true" />待审草稿</span><p>{{ source.draft }}</p></div>
          <div class="source-file"><span><FileText :size="16" aria-hidden="true" />{{ source.mode === 'standard_document' ? '对照标准' : '审核依据' }}</span><p>{{ source.standard ?? '制度知识库' }}</p></div>
          <p class="source-footnote">审核依据仅用于本次任务</p>
        </div>
        <div class="save-note"><Download :size="21" aria-hidden="true" /><h3>留下一份，方便继续。</h3><p>当前结果临时保留。下载 Word 后，可在本地继续修改与流转。</p></div>
      </aside>
    </div>
  </section>
</template>
