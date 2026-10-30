<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { LoaderCircle, MessagesSquare } from '@lucide/vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AgentCallResult from './AgentCallResult.vue'
import ConversationAttachments from './ConversationAttachments.vue'
import type { FileView, MessageView } from './types'
const props = defineProps<{ messages: MessageView[]; files: FileView[]; busy: boolean; stage: string; streamingText: string; sessionId: string | null; earlier: boolean; loadingEarlier: boolean }>()
const emit = defineEmits<{ 'load-earlier': [] }>()
const viewport = ref<HTMLElement>()
let anchor: { id: string; offset: number } | null = null
function loadEarlier() {
  const el = viewport.value
  if (el) {
    const items = [...el.querySelectorAll<HTMLElement>('[data-message-id]')]
    const item = items.find(item => item.getBoundingClientRect().bottom > el.getBoundingClientRect().top)
    if (item) anchor = { id: item.dataset.messageId!, offset: item.getBoundingClientRect().top - el.getBoundingClientRect().top }
  }
  follow = false
  emit('load-earlier')
}
let follow = true
const html = (text: string) => DOMPurify.sanitize(marked.parse(text, { async: false }))
function onScroll() {
  const el = viewport.value
  if (el) follow = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}
watch(() => props.sessionId, () => { follow = true; anchor = null })
watch(() => [props.messages, props.busy, props.streamingText], async () => {
  await nextTick()
  if (anchor && viewport.value) {
    const item = [...viewport.value.querySelectorAll<HTMLElement>('[data-message-id]')].find(item => item.dataset.messageId === anchor!.id)
    if (item) viewport.value.scrollTop += item.getBoundingClientRect().top - viewport.value.getBoundingClientRect().top - anchor.offset
    anchor = null
    return
  }
  if (follow && viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
}, { immediate: true, flush: 'post' })
</script>

<template>
  <div ref="viewport" class="messages" role="log" aria-label="会话消息" aria-live="polite" @scroll="onScroll">
    <button v-if="earlier" class="text-button" type="button" :disabled="loadingEarlier" @click="loadEarlier">{{ loadingEarlier ? '正在加载…' : '加载更早消息' }}</button>
    <article v-for="message in messages" :key="message.message_id" :data-message-id="message.message_id" class="message" :class="message.role">
      <div v-if="message.role === 'assistant'" class="assistant-label"><MessagesSquare :size="20" aria-hidden="true" /><span>会话助手</span></div>
      <div class="message-main">
        <ConversationAttachments v-if="message.file_ids.length" :files="files" :selected-ids="message.file_ids" readonly />
        <div v-if="message.role === 'user'" class="user-text">{{ message.content }}</div>
        <div v-else class="markdown-content assistant-text" v-html="html(message.content)"></div>
        <AgentCallResult v-if="message.agent_call" :call="message.agent_call" />
      </div>
    </article>
    <article v-if="streamingText" class="message assistant" aria-label="正在生成的回答" aria-busy="true">
      <div class="assistant-label"><MessagesSquare :size="20" aria-hidden="true" /><span>会话助手</span></div>
      <div class="message-main"><div class="markdown-content assistant-text" v-html="html(streamingText)"></div></div>
    </article>
    <div v-if="busy" class="working" role="status"><LoaderCircle class="spin" :size="18" aria-hidden="true" />{{ stage || '正在处理…' }}</div>
  </div>
</template>
