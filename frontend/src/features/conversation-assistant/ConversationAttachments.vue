<script setup lang="ts">
import type { DocumentView } from './types'
const props = defineProps<{ documents: DocumentView[]; selectedIds: string[]; uploading: boolean; disabled: boolean }>()
const emit = defineEmits<{ 'update:selectedIds': [value: string[]] }>()
function toggle(id: string) {
  emit('update:selectedIds', props.selectedIds.includes(id) ? props.selectedIds.filter(item => item !== id) : [...props.selectedIds, id])
}
</script>
<template>
  <details v-if="documents.length || uploading" class="attachments" open>
    <summary>会话材料 <span>{{ documents.length }} 份</span></summary>
    <div class="document-list">
      <label v-for="document in documents" :key="document.id" :class="{ selected: selectedIds.includes(document.id) }">
        <input type="checkbox" :checked="selectedIds.includes(document.id)" :disabled="disabled" @change="toggle(document.id)" />
        <span class="doc-icon" aria-hidden="true">W</span>
        <span class="doc-name">{{ document.filename }}<small>{{ document.chars.toLocaleString() }} 字符</small></span>
      </label>
      <span v-if="uploading" role="status" class="uploading">正在读取文档…</span>
    </div>
  </details>
</template>
<style scoped>
.attachments { margin: 0 0 12px; font-size: 12px; }
summary { cursor: pointer; color: var(--ink-soft); margin-bottom: 10px; }
summary span { margin-left: 5px; color: var(--muted); }
.document-list { display: flex; flex-wrap: wrap; gap: 8px; max-height: 150px; overflow-y: auto; }
label { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); background: #ffffff80; border-radius: 11px; padding: 9px 11px; cursor: pointer; min-width: 0; max-width: 100%; }
label.selected { border-color: #d9c4b6; background: #f0e9df; }
input { accent-color: var(--chat-accent); }
.doc-icon { font-family: Georgia, serif; color: #ac7356; font-size: 20px; }
.doc-name { overflow: hidden; overflow-wrap: anywhere; }
small { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
.uploading { color: var(--muted); padding: 12px; }
</style>
