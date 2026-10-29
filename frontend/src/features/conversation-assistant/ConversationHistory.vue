<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ArrowLeft, CircleQuestionMark, MessagesSquare, Plus, X } from '@lucide/vue'
import PlatformBrand from '../../components/PlatformBrand.vue'
import type { ConversationSummary } from './types'

defineProps<{ conversations: ConversationSummary[]; activeId: string | null; disabled: boolean; closable?: boolean }>()
const emit = defineEmits<{ select: [id: string]; new: []; close: [] }>()
</script>

<template>
  <div class="conversation-history">
    <div class="row between"><PlatformBrand /><button v-if="closable" class="icon-button" type="button" aria-label="关闭会话记录" @click="emit('close')"><X :size="19" aria-hidden="true" /></button></div>
    <RouterLink class="history-back" to="/agents" @click="emit('close')"><ArrowLeft :size="16" aria-hidden="true" />返回智能体目录</RouterLink>
    <button class="button history-new" type="button" :disabled="disabled" @click="emit('new')"><Plus :size="18" aria-hidden="true" />新建对话</button>
    <div class="history-section">
      <p class="history-label">会话记录</p>
      <nav class="history-list" aria-label="会话记录">
        <button v-for="conversation in conversations" :key="conversation.id" class="history-item" type="button"
          :class="{ active: conversation.id === activeId }" :aria-current="conversation.id === activeId ? 'page' : undefined"
          :disabled="disabled" @click="emit('select', conversation.id)">
          <MessagesSquare :size="17" aria-hidden="true" /><span>{{ conversation.title }}</span>
        </button>
        <p v-if="!conversations.length" class="history-empty">连接后即可开始对话。</p>
      </nav>
    </div>
    <p class="history-note"><CircleQuestionMark :size="17" aria-hidden="true" /><span>历史记录仅在当前页面内保留。<br />重要结果请及时保存。</span></p>
  </div>
</template>
