<script setup lang="ts">
import { computed } from 'vue'
import { CircleAlert, CircleCheck, ShieldCheck } from '@lucide/vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { AgentCallView } from './types'
const props = defineProps<{ call: AgentCallView }>()
const html = computed(() => props.call.output_type === 'markdown' ? DOMPurify.sanitize(marked.parse(props.call.output ?? '', { async: false })) : '')
const labels = { queued: '等待处理', running: '执行中', succeeded: '已完成', failed: '执行失败', cancelled: '已停止' }
</script>

<template>
  <section class="agent-result" :aria-label="`${call.agent_name}执行结果`">
    <header><ShieldCheck :size="19" aria-hidden="true" /><strong>{{ call.agent_name }}</strong><span class="badge" :class="call.status === 'succeeded' ? 'badge-success' : ''"><CircleCheck v-if="call.status === 'succeeded'" :size="14" aria-hidden="true" />{{ labels[call.status] }}</span></header>
    <div v-if="call.output_type === 'markdown'" class="markdown-content" v-html="html"></div>
    <pre v-else class="text-result">{{ call.output }}</pre>
    <p v-if="call.error" class="field-error" role="alert"><CircleAlert :size="17" aria-hidden="true" />{{ call.error.message }}</p>
  </section>
</template>
