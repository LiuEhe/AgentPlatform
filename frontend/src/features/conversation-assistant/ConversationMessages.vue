<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AgentCallResult from './AgentCallResult.vue'
import type { MessageView } from './types'
const props = defineProps<{ messages: MessageView[]; busy: boolean; stage: string }>()
const viewport = ref<HTMLElement>()
let follow = true
const html = (text: string) => DOMPurify.sanitize(marked.parse(text, { async: false }))
function onScroll() {
  const el = viewport.value
  if (el) follow = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}
watch(() => [props.messages.length, props.busy], async () => {
  await nextTick()
  if (follow && viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
})
</script>
<template>
  <div ref="viewport" class="messages" role="log" aria-label="会话消息" aria-live="polite" @scroll="onScroll">
    <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
      <svg v-if="message.role === 'assistant'" class="assistant-mark" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 1c1.8 9.3 5.7 13.2 15 15-9.3 1.8-13.2 5.7-15 15C14.2 21.7 10.3 17.8 1 16 10.3 14.2 14.2 10.3 16 1Z" /></svg>
      <div class="message-main">
        <div v-if="message.role === 'user'" class="user-text">{{ message.content }}</div>
        <div v-else class="assistant-text" v-html="html(message.content)"></div>
        <div v-if="message.document_ids.length" class="message-attachments">附带 {{ message.document_ids.length }} 份材料</div>
        <AgentCallResult v-if="message.agent_call" :call="message.agent_call" />
      </div>
    </article>
    <div v-if="busy" class="working" role="status"><span aria-hidden="true">✳</span>{{ stage || '正在处理…' }}</div>
  </div>
</template>
<style scoped>
.messages { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 10px 28px 0; scroll-behavior: auto; scrollbar-width: thin; scrollbar-color: #d9d4c9 transparent; }
.message { display: flex; gap: 13px; margin: 24px 0 32px; }
.message-main { min-width: 0; flex: 1; }
.assistant-mark { flex: 0 0 24px; height: 24px; margin-top: 6px; color: var(--chat-accent); }
.assistant-text { font-size: 15px; line-height: 1.9; overflow-wrap: anywhere; }
.assistant-text :deep(p:first-child) { margin-top: 4px; }
.assistant-text :deep(pre) { overflow-x: auto; background: #eeece7; border-radius: 8px; padding: 14px; }
.assistant-text :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; }
.assistant-text :deep(td), .assistant-text :deep(th) { border: 1px solid var(--line); padding: 6px 10px; }
.user { justify-content: flex-end; }
.user .message-main { flex: 0 1 auto; max-width: 85%; }
.user-text { white-space: pre-wrap; overflow-wrap: anywhere; background: #eeebe4; padding: 12px 18px; border-radius: 18px; font-size: 14px; line-height: 1.8; }
.message-attachments { color: var(--muted); font-size: 11px; margin-top: 7px; text-align: right; }
.working { display: flex; align-items: center; gap: 12px; color: var(--ink-soft); font-size: 13px; padding-bottom: 15px; }
.working span { color: var(--chat-accent); font-size: 23px; }
</style>
