<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { LoaderCircle, MessagesSquare } from '@lucide/vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AgentCallResult from './AgentCallResult.vue'
import ConversationAttachments from './ConversationAttachments.vue'
import type { DocumentView, MessageView } from './types'
const props = defineProps<{ messages: MessageView[]; documents: DocumentView[]; busy: boolean; stage: string }>()
const viewport = ref<HTMLElement>()
let follow = true
const html = (text: string) => DOMPurify.sanitize(marked.parse(text, { async: false }))
function onScroll() {
  const el = viewport.value
  if (el) follow = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}
watch(() => props.messages[0]?.id, () => { follow = true })
watch(() => [props.messages, props.busy], async () => {
  await nextTick()
  if (follow && viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
}, { immediate: true, flush: 'post' })
</script>

<template>
  <div ref="viewport" class="messages" role="log" aria-label="会话消息" aria-live="polite" @scroll="onScroll">
    <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
      <div v-if="message.role === 'assistant'" class="assistant-label"><MessagesSquare :size="20" aria-hidden="true" /><span>会话助手</span></div>
      <div class="message-main">
        <ConversationAttachments v-if="message.document_ids.length" :documents="documents" :selected-ids="message.document_ids" readonly />
        <div v-if="message.role === 'user'" class="user-text">{{ message.content }}</div>
        <div v-else class="markdown-content assistant-text" v-html="html(message.content)"></div>
        <AgentCallResult v-if="message.agent_call" :call="message.agent_call" />
      </div>
    </article>
    <div v-if="busy" class="working" role="status"><LoaderCircle class="spin" :size="18" aria-hidden="true" />{{ stage || '正在处理…' }}</div>
  </div>
</template>
