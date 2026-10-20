<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { AgentCallView } from './types'
const props = defineProps<{ call: AgentCallView }>()
const html = computed(() => props.call.output_type === 'markdown' ? DOMPurify.sanitize(marked.parse(props.call.output ?? '', { async: false })) : '')
</script>
<template>
  <section class="agent-result" :aria-label="`${call.agent_name}执行结果`">
    <header><span class="result-dot" aria-hidden="true"></span><strong>{{ call.agent_name }}</strong><span class="result-status">{{ call.status === 'succeeded' ? '已完成' : '处理未完成' }}</span></header>
    <div v-if="call.output_type === 'markdown'" class="result-body" v-html="html"></div>
    <pre v-else class="text-result">{{ call.output }}</pre>
    <p v-if="call.error" role="alert">{{ call.error.message }}</p>
  </section>
</template>
<style scoped>
.agent-result { border: 1px solid var(--line); background: var(--white); border-radius: 14px; margin-top: 16px; overflow: hidden; }
header { display: flex; align-items: center; gap: 8px; padding: 14px 17px; background: #f2efe8; font-size: 12px; border-bottom: 1px solid var(--line); }
.result-dot { width: 7px; height: 7px; background: var(--success); border-radius: 50%; }
.result-status { margin-left: auto; color: var(--success); font-size: 11px; }
.result-body { padding: 8px 19px 18px; overflow-x: auto; overflow-wrap: anywhere; font-size: 14px; line-height: 1.8; }
.result-body :deep(table) { border-collapse: collapse; min-width: 100%; font-size: 12px; }
.result-body :deep(th), .result-body :deep(td) { padding: 8px; border: 1px solid var(--line); }
.result-body :deep(pre) { overflow-x: auto; padding: 12px; background: var(--paper); }
.text-result { padding: 18px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
