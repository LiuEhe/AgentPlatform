<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowUp, Paperclip, Square } from '@lucide/vue'
const props = defineProps<{ modelValue: string; disabled: boolean; canStop: boolean; hasAttachments?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; send: []; attach: []; stop: [] }>()
const composing = ref(false)
const canSend = computed(() => !props.disabled && (Boolean(props.modelValue.trim()) || props.hasAttachments))
function onKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing.value && event.keyCode !== 229) {
    event.preventDefault()
    if (canSend.value) emit('send')
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="canSend && emit('send')">
    <slot />
    <textarea :value="modelValue" :disabled="disabled" rows="2" maxlength="12000"
      aria-label="消息" :placeholder="hasAttachments ? '为文件补充一句说明，或直接发送…' : '说说你想完成的事，也可以直接粘贴正文…'"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @keydown="onKey" @compositionstart="composing = true" @compositionend="composing = false" />
    <div class="composer-tools">
      <button class="attach-button" type="button" :disabled="disabled" @click="emit('attach')"><Paperclip :size="18" aria-hidden="true" />添加文件</button>
      <span class="keyboard-hint">Enter 发送<span> · Shift + Enter 换行</span></span>
      <button v-if="canStop" type="button" class="send-button stop-button" aria-label="停止处理" @click="emit('stop')"><Square :size="18" aria-hidden="true" /></button>
      <button v-else type="submit" class="send-button" aria-label="发送消息" :disabled="!canSend"><ArrowUp :size="21" aria-hidden="true" /></button>
    </div>
  </form>
</template>
