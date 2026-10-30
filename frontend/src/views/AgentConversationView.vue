<script setup lang="ts">
import { nextTick, onActivated, onDeactivated, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowLeft, ArrowUpRight, CircleAlert, Menu, MessagesSquare } from '@lucide/vue'
import ConversationComposer from '../features/conversation-assistant/ConversationComposer.vue'
import ConversationMessages from '../features/conversation-assistant/ConversationMessages.vue'
import ConversationAttachments from '../features/conversation-assistant/ConversationAttachments.vue'
import ConversationHistory from '../features/conversation-assistant/ConversationHistory.vue'
import { useConversation } from '../features/conversation-assistant/useConversation'

defineOptions({ name: 'AgentConversationView' })
const { sessionId, sessions, messages, files, selectedFileIds, draft, activeRun, streamingText, busy,
  initializing, uploading, error, retryable, initialize, send, upload, stop, newSession,
  deleting, canDelete, pendingDeletions, deletionError, deleteSession, retryDeletion, hasDraft,
  switchSession, suspend, retry, loadMoreSessions, loadEarlierMessages, hasMoreSessions, hasEarlierMessages, loadingHistory, loadingEarlier } = useConversation()
const fileInput = ref<HTMLInputElement>()
const historyDialog = ref<HTMLDialogElement>()
const deletionDialog = ref<HTMLDialogElement>()
const cancelDeletionButton = ref<HTMLButtonElement>()
const deletionTarget = ref<{ id: string; title: string; hasDraft: boolean } | null>(null)
let deletionTrigger: HTMLElement | null = null
const prompts = ['你好，介绍一下你自己', '帮我写一封会议邀请', '聊聊怎么整理工作思路']
onActivated(() => { void initialize() })
onDeactivated(() => { historyDialog.value?.close(); deletionDialog.value?.close(); suspend() })
function attach(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void upload(file)
  input.value = ''
}
function select(id: string) { historyDialog.value?.close(); void switchSession(id) }
function create() { historyDialog.value?.close(); void newSession() }
async function requestDeletion(id: string) {
  if (!canDelete.value) return
  const target = sessions.value.find(item => item.session_id === id)
  if (!target) return
  deletionTrigger = historyDialog.value?.open
    ? document.querySelector<HTMLElement>('.mobile-history') : document.activeElement as HTMLElement | null
  historyDialog.value?.close()
  deletionTarget.value = { id, title: target.title, hasDraft: hasDraft(id) }
  deletionDialog.value?.showModal()
  await nextTick()
  cancelDeletionButton.value?.focus()
}
function closeDeletion() {
  deletionTarget.value = null
  deletionTrigger?.focus()
}
async function confirmDeletion() {
  const id = deletionTarget.value?.id
  if (!id || !canDelete.value) return
  deletionDialog.value?.close()
  await deleteSession(id)
}
</script>

<template>
  <section class="conversation-page">
    <aside class="conversation-sidebar">
      <ConversationHistory :sessions="sessions" :active-id="sessionId" :disabled="initializing || deleting" :delete-disabled="!canDelete" :has-more="hasMoreSessions" :loading="loadingHistory" @more="loadMoreSessions" @select="select" @delete="requestDeletion" @new="create" />
    </aside>
    <div class="conversation-main">
      <header class="conversation-header">
        <div class="row">
          <button class="icon-button mobile-history" type="button" aria-label="打开会话记录" @click="historyDialog?.showModal()"><Menu :size="20" aria-hidden="true" /></button>
          <RouterLink class="back-link" to="/agents"><ArrowLeft :size="16" aria-hidden="true" />智能体</RouterLink><span class="breadcrumb-separator">/</span><span>会话助手</span>
        </div>
        <span class="badge">会话助手</span>
      </header>
      <div class="chat-column" :class="{ 'is-empty': !messages.length }">
        <div v-if="!messages.length" class="chat-welcome">
          <div class="eyebrow"><MessagesSquare :size="21" aria-hidden="true" />会话助手</div>
          <h1>有什么想一起聊聊的？</h1>
          <p>{{ sessionId ? '提问、写作，或整理一段材料。你可以从任何问题开始。' : '暂无会话，点击新建对话开始。' }}</p>
        </div>
        <template v-else>
          <div class="dialogue-heading"><h1>会话助手</h1><span class="muted small">已加载 {{ messages.length }} 条消息</span></div>
          <ConversationMessages :session-id="sessionId" :earlier="hasEarlierMessages" :loading-earlier="loadingEarlier" @load-earlier="loadEarlierMessages" :messages="messages" :files="files" :busy="busy && !initializing && !uploading" :stage="activeRun?.stage ?? ''" :streaming-text="streamingText" />
        </template>
        <div class="input-dock">
          <div v-if="deletionError" class="conversation-error" role="alert"><CircleAlert :size="18" aria-hidden="true" /><span>{{ deletionError }}</span></div>
          <div v-for="item in pendingDeletions" :key="item.session_id" class="conversation-error" role="status">
            <span>{{ item.phase === 'cleanup_pending' ? '有一段对话的附件尚待清理。' : '有一段对话的删除结果尚未确认。' }}</span>
            <button class="text-button" type="button" :disabled="!canDelete" @click="retryDeletion(item.session_id)">{{ item.phase === 'cleanup_pending' ? '重试清理' : '重试删除' }}</button>
          </div>
          <div v-if="error" class="conversation-error" role="alert">
            <CircleAlert :size="18" aria-hidden="true" /><span>{{ error }}</span><button v-if="retryable" class="text-button" type="button" @click="retry">重试</button>
          </div>
          <ConversationComposer v-model="draft" :disabled="busy || !sessionId" :has-attachments="selectedFileIds.length > 0"
            :can-stop="Boolean(!deleting && !initializing && activeRun && !['succeeded', 'failed', 'cancelled'].includes(activeRun.status))"
            @send="send" @attach="fileInput?.click()" @stop="stop">
            <ConversationAttachments v-model:selected-ids="selectedFileIds" :files="files" :uploading="uploading" :disabled="busy" />
          </ConversationComposer>
          <input ref="fileInput" class="visually-hidden" type="file" accept=".docx" aria-label="选择 Word 文档" @change="attach" />
          <p v-if="initializing" class="input-note" role="status">正在连接会话…</p>
          <p v-else class="input-note">文件随消息展示 · 会话历史已保存</p>
        </div>
        <div v-if="!messages.length" class="prompts">
          <button v-for="prompt in prompts" :key="prompt" class="prompt" type="button" :disabled="busy || !sessionId" @click="draft = prompt">{{ prompt }}<ArrowUpRight :size="14" aria-hidden="true" /></button>
        </div>
      </div>
    </div>
    <dialog ref="historyDialog" class="history-dialog" aria-label="会话记录" @click="($event.target === historyDialog) && historyDialog?.close()">
      <ConversationHistory :sessions="sessions" :active-id="sessionId" :disabled="initializing || deleting" :delete-disabled="!canDelete" :has-more="hasMoreSessions" :loading="loadingHistory" @more="loadMoreSessions" closable @select="select" @delete="requestDeletion" @new="create" @close="historyDialog?.close()" />
    </dialog>
    <dialog ref="deletionDialog" class="confirm-dialog" aria-labelledby="delete-session-title" @close="closeDeletion" @click="($event.target === deletionDialog) && deletionDialog?.close()">
      <form @submit.prevent="confirmDeletion">
        <h2 id="delete-session-title">永久删除对话？</h2>
        <p class="deletion-title">{{ deletionTarget?.title }}</p>
        <p>将永久删除此对话、消息和上传文件，无法恢复。</p>
        <p v-if="deletionTarget?.hasDraft">此对话尚未发送的草稿也将被清除。</p>
        <div class="dialog-actions">
          <button ref="cancelDeletionButton" class="button" type="button" autofocus @click="deletionDialog?.close()">取消</button>
          <button class="button button-danger" type="submit" :disabled="!canDelete">永久删除</button>
        </div>
      </form>
    </dialog>
  </section>
</template>
