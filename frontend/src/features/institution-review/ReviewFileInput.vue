<script setup lang="ts">
import { ref, watch } from 'vue'
import { FileText, Upload, X } from '@lucide/vue'
const props = defineProps<{ id: string; label: string; file: File | null; error: string; disabled?: boolean }>()
const emit = defineEmits<{ select: [file: File | null] }>()
const input = ref<HTMLInputElement>()
const dragging = ref(false)
watch(() => props.file, file => { if (!file && input.value) input.value.value = '' })
function drop(event: DragEvent) {
  dragging.value = false
  if (props.disabled) return
  const files = event.dataTransfer?.files
  if (files?.length) emit('select', files[0] ?? null)
}
</script>

<template>
  <div class="review-file-field" :class="{ 'is-dragging': dragging && !disabled }"
    @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
    <input :id="id" ref="input" class="visually-hidden" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      :aria-label="label" :disabled="disabled" :aria-invalid="Boolean(error)" :aria-describedby="error ? id + '-error' : undefined"
      @change="emit('select', ($event.target as HTMLInputElement).files?.[0] ?? null)" />
    <div v-if="file" class="review-file">
      <span class="file-symbol"><FileText :size="24" aria-hidden="true" /></span>
      <div class="file-description"><strong>{{ file.name }}</strong><span>{{ label }} · {{ (file.size / 1024).toFixed(1) }} KB</span></div>
      <button class="icon-button" type="button" :disabled="disabled" :aria-label="'移除' + label" @click="emit('select', null)"><X :size="18" aria-hidden="true" /></button>
    </div>
    <label v-else class="dropzone" :class="{ 'dropzone-disabled': disabled }" :for="id">
      <Upload :size="27" :stroke-width="1.75" aria-hidden="true" /><strong>拖入{{ label }}，或点击选择</strong><span>仅支持 DOCX · {{ label === '标准文档' ? '作为本次审核的对照依据' : '选择需要审核的制度草稿' }}</span>
    </label>
    <p v-if="error" :id="id + '-error'" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>
