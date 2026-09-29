<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps<{ markdown: string }>()

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
      <span class="report-ready"><span class="report-ready-dot"></span> 已生成</span>
    </div>
    <div class="markdown-content" v-html="safeHtml"></div>
  </section>
</template>
