<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import ConversationComposer from '../features/conversation-assistant/ConversationComposer.vue'
import ConversationMessages from '../features/conversation-assistant/ConversationMessages.vue'
import ConversationAttachments from '../features/conversation-assistant/ConversationAttachments.vue'
import { useConversation } from '../features/conversation-assistant/useConversation'
const { conversationId, messages, documents, selectedDocumentIds, draft, activeRun, busy,
  initializing, uploading, error, retryable, initialize, send, upload, stop, newConversation, retry } = useConversation()
const fileInput = ref<HTMLInputElement>()
onMounted(initialize)
function attach(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void upload(file)
  input.value = ''
}
</script>

<template>
  <section class="conversation-page">
    <header class="conversation-heading">
      <RouterLink class="agent-wordmark" to="/agents" aria-label="Agent，返回智能体广场">Agent</RouterLink>
      <button class="new-chat" type="button" :disabled="initializing" @click="newConversation">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-6M16 4l4 4M10 14l1-4 7-7a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2l-7 7-4 1Z" /></svg>
        <span>新建对话</span>
      </button>
    </header>
    <div class="chat-column" :class="{ 'is-empty': !messages.length }">
      <div v-if="!messages.length" class="chat-welcome">
        <h1>
          <svg class="welcome-mark" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 1c1.8 9.3 5.7 13.2 15 15-9.3 1.8-13.2 5.7-15 15C14.2 21.7 10.3 17.8 1 16 10.3 14.2 14.2 10.3 16 1Z" /></svg>
          <span>有什么可以帮你？</span>
        </h1>
        <p>从一个问题开始，和你的智能助手聊聊。</p>
      </div>
      <ConversationMessages v-else :messages="messages" :busy="busy && !uploading" :stage="activeRun?.stage ?? ''" />
      <div class="input-dock">
        <ConversationAttachments v-model:selected-ids="selectedDocumentIds" :documents="documents" :uploading="uploading" :disabled="busy" />
        <div v-if="error" class="conversation-error" role="alert">
          <span>{{ error }}</span><button v-if="retryable" type="button" @click="retry">重试</button>
        </div>
        <ConversationComposer v-model="draft" :disabled="busy || !conversationId" :can-stop="Boolean(activeRun && !['succeeded', 'failed', 'cancelled'].includes(activeRun.status))"
          @send="send" @attach="fileInput?.click()" @stop="stop" />
        <input ref="fileInput" class="file-input" type="file" accept=".docx" aria-label="选择 Word 文档" @change="attach" />
        <p v-if="initializing" class="input-note" role="status">正在连接会话…</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.conversation-page {
  --ink: #292720;
  --ink-soft: #6b6860;
  --muted: #aaa69c;
  --paper: #f8f6f1;
  --line: #e6e2d9;
  --chat-accent: #d57859;
  --chat-hover: #efebe3;
  --chat-focus: #d6b9a7;
  height: 100dvh;
  min-height: 440px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ink);
  background: var(--paper);
}
.conversation-page :deep(button:focus-visible), .conversation-page :deep(a:focus-visible),
.conversation-page :deep(summary:focus-visible), .conversation-page :deep(input:focus-visible) {
  outline: 2px solid var(--chat-focus);
  outline-offset: 4px;
}
.conversation-heading { height: 68px; flex: 0 0 auto; padding: 0 30px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.agent-wordmark { font-family: Georgia, 'Times New Roman', serif; font-size: 23px; letter-spacing: -.6px; text-decoration: none; }
.new-chat { display: inline-flex; align-items: center; gap: 8px; background: transparent; border: 0; color: #78746b; padding: 9px 11px; font-size: 12px; border-radius: 9px; cursor: pointer; }
.new-chat svg { height: 17px; width: 17px; stroke: currentColor; stroke-width: 1.45; stroke-linecap: round; stroke-linejoin: round; }
.new-chat:hover { background: var(--chat-hover); color: var(--ink); }
.new-chat:disabled { opacity: .45; cursor: default; }
.chat-column { position: relative; width: min(900px, calc(100% - 64px)); min-height: 0; flex: 1; margin: 0 auto; display: flex; flex-direction: column; }
.chat-welcome { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding-bottom: clamp(50px, 10vh, 108px); }
.chat-welcome h1 { display: flex; align-items: center; gap: 15px; margin: 0; font-family: Georgia, 'Noto Serif SC', 'Songti SC', SimSun, serif; font-size: clamp(31px, 3vw, 42px); font-weight: 400; letter-spacing: -.7px; line-height: 1.4; }
.welcome-mark { flex: 0 0 auto; width: 29px; height: 29px; color: var(--chat-accent); }
.chat-welcome > p { font-size: 16px; color: #9c988e; line-height: 1.8; margin: 15px 0 0; text-align: center; }
.input-dock { flex: 0 0 auto; padding-bottom: max(48px, env(safe-area-inset-bottom)); }
.input-note { font-size: 11px; color: var(--muted); text-align: center; margin: 12px 0 -29px; }
.file-input { display: none; }
.conversation-error { display: flex; align-items: center; gap: 10px; background: #f5eae4; color: #98513e; border-radius: 9px; padding: 10px 13px; margin-bottom: 12px; font-size: 12px; line-height: 1.7; }
.conversation-error button { margin-left: auto; border: 0; background: white; color: var(--danger); border-radius: 5px; padding: 5px 9px; flex-shrink: 0; cursor: pointer; }
@media (max-width: 600px) {
  .conversation-heading { height: 60px; padding: 0 19px; }
  .agent-wordmark { font-size: 21px; }
  .chat-column { width: calc(100% - 32px); }
  .chat-welcome { padding: 0 0 60px; }
  .chat-welcome h1 { gap: 10px; font-size: clamp(26px, 6.6vw, 35px); letter-spacing: -.5px; }
  .welcome-mark { width: 23px; height: 23px; }
  .chat-welcome > p { max-width: 280px; font-size: 13px; margin-top: 14px; }
  .input-dock { padding-bottom: max(20px, env(safe-area-inset-bottom)); }
}
@media (max-height: 550px) { .chat-welcome { padding-bottom: 16px; } .input-dock { padding-bottom: 16px; } }
</style>
