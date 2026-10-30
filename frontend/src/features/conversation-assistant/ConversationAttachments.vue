<script setup lang="ts">
import { computed } from 'vue'
import { FileText, LoaderCircle, X } from '@lucide/vue'
import type { FileView } from './types'
const props = withDefaults(defineProps<{
  files: FileView[]; selectedIds: string[]; uploading?: boolean; disabled?: boolean; readonly?: boolean
}>(), { uploading: false, disabled: false, readonly: false })
const emit = defineEmits<{ 'update:selectedIds': [value: string[]] }>()
const selected = computed(() => props.selectedIds.map(id => props.files.find(document => document.file_id === id) ??
  { file_id: id, original_name: '已附加文档', size_bytes: 0, content_chars: 0, created_at: '' }))
function remove(id: string) {
  emit('update:selectedIds', props.selectedIds.filter(item => item !== id))
}
</script>

<template>
  <div v-if="selected.length || uploading" class="attachment-list" :aria-label="readonly ? '消息中的文件' : '待发送文件'">
    <span v-for="document in selected" :key="document.file_id" class="attachment-card">
      <FileText :size="20" aria-hidden="true" /><span class="attachment-name" :title="document.original_name">{{ document.original_name }}</span>
      <span class="attachment-format">DOCX</span>
      <button v-if="!readonly" class="icon-button" type="button" :disabled="disabled" :aria-label="'移除文件 ' + document.original_name" @click="remove(document.file_id)"><X :size="16" aria-hidden="true" /></button>
    </span>
    <span v-if="uploading" class="uploading" role="status"><LoaderCircle class="spin" :size="17" aria-hidden="true" />正在读取文档…</span>
  </div>
</template>
