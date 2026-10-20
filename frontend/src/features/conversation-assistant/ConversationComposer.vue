<script setup lang="ts">
import { ref } from 'vue'
defineProps<{ modelValue: string; disabled: boolean; canStop: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: string]; send: []; attach: []; stop: []
}>()
const composing = ref(false)
function onKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing.value && event.keyCode !== 229) {
    event.preventDefault()
    emit('send')
  }
}
</script>

<template>
  <div class="composer">
    <textarea :value="modelValue" :disabled="disabled" rows="1" maxlength="12000"
      aria-label="消息" placeholder="发送消息…"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @keydown="onKey" @compositionstart="composing = true" @compositionend="composing = false" />
    <div class="composer-tools">
      <button class="attach" type="button" :disabled="disabled" @click="emit('attach')" aria-label="添加 Word 文档">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9M7 14l8-8" /></svg>
      </button>
      <span class="keyboard-hint">Enter 发送 · Shift + Enter 换行</span>
      <button v-if="canStop" type="button" class="send stop" aria-label="停止处理" @click="emit('stop')">■</button>
      <button v-else type="button" class="send" aria-label="发送消息" :disabled="disabled || !modelValue.trim()" @click="emit('send')">↑</button>
    </div>
  </div>
</template>

<style scoped>
.composer { background: #fff; border: 1px solid var(--line); border-radius: 28px; padding: 20px 16px 13px 24px; box-shadow: 0 2px 4px #29272003; }
.composer:focus-within { border-color: var(--chat-focus); box-shadow: 0 2px 10px #29272005; }
textarea { display: block; width: 100%; min-height: 42px; max-height: 180px; resize: vertical; border: 0; outline: 0; background: transparent; color: var(--ink); font: inherit; font-size: 16px; line-height: 1.65; }
textarea::placeholder { color: var(--muted); }
.composer-tools { display: flex; align-items: center; gap: 9px; margin-top: 5px; }
button { border: 0; cursor: pointer; }
.attach { display: grid; place-items: center; width: 30px; height: 30px; flex: 0 0 auto; color: #aaa69b; background: none; padding: 5px; margin-left: -5px; border-radius: 8px; }
.attach:hover { background: var(--chat-hover); color: var(--ink-soft); }
.attach svg { width: 18px; height: 18px; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.keyboard-hint { font-size: 11px; color: #b3aea3; }
.send { margin-left: auto; display: grid; place-items: center; width: 39px; height: 39px; flex: 0 0 auto; border-radius: 50%; background: var(--chat-accent); color: white; font-size: 25px; line-height: 1; }
.stop { font-size: 13px; }
.send:disabled { background: #ede9df; color: #c6c0b2; cursor: default; }
.attach:disabled { opacity: .45; cursor: default; }
@media (max-width: 600px) {
  .composer { border-radius: 23px; padding: 17px 13px 11px 19px; }
  .keyboard-hint { font-size: 10px; }
  .send { width: 35px; height: 35px; }
}
</style>
