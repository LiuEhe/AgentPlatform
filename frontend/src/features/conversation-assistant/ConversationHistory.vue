<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ArrowLeft, CircleQuestionMark, MessagesSquare, Plus, Trash2, X } from '@lucide/vue'
import PlatformBrand from '../../components/PlatformBrand.vue'
import type { SessionSummary } from './types'

defineProps<{ sessions: SessionSummary[]; activeId: string | null; disabled: boolean; deleteDisabled: boolean; closable?: boolean; hasMore: boolean; loading: boolean }>()
const emit = defineEmits<{ select: [id: string]; delete: [id: string]; new: []; close: []; more: [] }>()
</script>

<template>
  <div class="conversation-history">
    <div class="row between"><PlatformBrand /><button v-if="closable" class="icon-button" type="button" aria-label="关闭会话记录" @click="emit('close')"><X :size="19" aria-hidden="true" /></button></div>
    <RouterLink class="history-back" to="/agents" @click="emit('close')"><ArrowLeft :size="16" aria-hidden="true" />返回智能体目录</RouterLink>
    <button class="button history-new" type="button" :disabled="disabled" @click="emit('new')"><Plus :size="18" aria-hidden="true" />新建对话</button>
    <div class="history-section">
      <p class="history-label">会话记录</p>
      <nav class="history-list" aria-label="会话记录">
        <div v-for="conversation in sessions" :key="conversation.session_id" class="history-row" :class="{ active: conversation.session_id === activeId }">
          <button class="history-item" type="button" :aria-current="conversation.session_id === activeId ? 'page' : undefined"
            :disabled="disabled" @click="emit('select', conversation.session_id)">
            <MessagesSquare :size="17" aria-hidden="true" /><span>{{ conversation.title }}</span>
          </button>
          <button class="icon-button history-delete" type="button" :disabled="deleteDisabled" :aria-label="`删除对话：${conversation.title}`" @click="emit('delete', conversation.session_id)"><Trash2 :size="16" aria-hidden="true" /></button>
        </div>
        <p v-if="!sessions.length" class="history-empty">暂无会话，点击新建对话开始。</p>
      </nav>
      <button v-if="hasMore" class="text-button" type="button" :disabled="disabled || loading" @click="emit('more')">{{ loading ? '正在加载…' : '加载更多' }}</button>
    </div>
    <p class="history-note"><CircleQuestionMark :size="17" aria-hidden="true" /><span>会话历史已保存。<br />可随时打开并继续对话。</span></p>
  </div>
</template>
