<script setup lang="ts">
import { onActivated, onDeactivated, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowLeft, ArrowUpRight, CircleAlert, Menu, MessagesSquare } from '@lucide/vue'
import ConversationComposer from '../features/conversation-assistant/ConversationComposer.vue'
import ConversationMessages from '../features/conversation-assistant/ConversationMessages.vue'
import ConversationAttachments from '../features/conversation-assistant/ConversationAttachments.vue'
import ConversationHistory from '../features/conversation-assistant/ConversationHistory.vue'
import { useConversation } from '../features/conversation-assistant/useConversation'

defineOptions({ name: 'AgentConversationView' })
const { conversationId, conversations, messages, documents, selectedDocumentIds, draft, activeRun, busy,
  initializing, uploading, error, retryable, initialize, send, upload, stop, newConversation,
  switchConversation, suspend, retry } = useConversation()
const fileInput = ref<HTMLInputElement>()
const historyDialog = ref<HTMLDialogElement>()
const prompts = ['你好，介绍一下你自己', '帮我写一封会议邀请', '聊聊怎么整理工作思路']
onActivated(() => { void initialize() })
onDeactivated(() => { historyDialog.value?.close(); suspend() })
function attach(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void upload(file)
  input.value = ''
}
function select(id: string) { historyDialog.value?.close(); void switchConversation(id) }
function create() { historyDialog.value?.close(); void newConversation() }
</script>

<template>
  <section class="conversation-page">
    <aside class="conversation-sidebar">
      <ConversationHistory :conversations="conversations" :active-id="conversationId" :disabled="initializing" @select="select" @new="create" />
    </aside>
    <div class="conversation-main">
      <header class="conversation-header">
        <div class="row">
          <button class="icon-button mobile-history" type="button" aria-label="打开会话记录" @click="historyDialog?.showModal()"><Menu :size="20" aria-hidden="true" /></button>
          <RouterLink class="back-link" to="/agents"><ArrowLeft :size="16" aria-hidden="true" />智能体</RouterLink><span class="breadcrumb-separator">/</span><span>会话助手</span>
        </div>
        <span class="badge">临时会话</span>
      </header>
      <div class="chat-column" :class="{ 'is-empty': !messages.length }">
        <div v-if="!messages.length" class="chat-welcome">
          <div class="eyebrow"><MessagesSquare :size="21" aria-hidden="true" />会话助手</div>
          <h1>有什么想一起聊聊的？</h1>
          <p>提问、写作，或整理一段材料。你可以从任何问题开始。</p>
        </div>
        <template v-else>
          <div class="dialogue-heading"><h1>会话助手</h1><span class="muted small">{{ messages.filter(message => message.role === 'user').length }} 轮对话</span></div>
          <ConversationMessages :messages="messages" :documents="documents" :busy="busy && !initializing && !uploading" :stage="activeRun?.stage ?? ''" />
        </template>
        <div class="input-dock">
          <div v-if="error" class="conversation-error" role="alert">
            <CircleAlert :size="18" aria-hidden="true" /><span>{{ error }}</span><button v-if="retryable" class="text-button" type="button" @click="retry">重试</button>
          </div>
          <ConversationComposer v-model="draft" :disabled="busy || !conversationId" :has-attachments="selectedDocumentIds.length > 0"
            :can-stop="Boolean(!initializing && activeRun && !['succeeded', 'failed', 'cancelled'].includes(activeRun.status))"
            @send="send" @attach="fileInput?.click()" @stop="stop">
            <ConversationAttachments v-model:selected-ids="selectedDocumentIds" :documents="documents" :uploading="uploading" :disabled="busy" />
          </ConversationComposer>
          <input ref="fileInput" class="visually-hidden" type="file" accept=".docx" aria-label="选择 Word 文档" @change="attach" />
          <p v-if="initializing" class="input-note" role="status">正在连接会话…</p>
          <p v-else class="input-note">文件随消息展示 · 历史记录仅在当前页面内保留</p>
        </div>
        <div v-if="!messages.length" class="prompts">
          <button v-for="prompt in prompts" :key="prompt" class="prompt" type="button" :disabled="busy" @click="draft = prompt">{{ prompt }}<ArrowUpRight :size="14" aria-hidden="true" /></button>
        </div>
      </div>
    </div>
    <dialog ref="historyDialog" class="history-dialog" aria-label="会话记录" @click="($event.target === historyDialog) && historyDialog?.close()">
      <ConversationHistory :conversations="conversations" :active-id="conversationId" :disabled="initializing" closable @select="select" @new="create" @close="historyDialog?.close()" />
    </dialog>
  </section>
</template>
