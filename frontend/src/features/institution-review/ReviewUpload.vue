<script setup lang="ts">
import { computed, ref, watch, type ComponentPublicInstance } from 'vue'
import type { ReviewMode, ReviewSubmission } from './types'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ submit: [submission: ReviewSubmission] }>()
type UploadRole = 'draft' | 'standard'
const mode = ref<ReviewMode>('knowledge_base')
const selectedFiles = ref<Record<UploadRole, File | null>>({ draft: null, standard: null })
const messages = ref<Record<UploadRole, string>>({ draft: '', standard: '' })
const fileInputs: Partial<Record<UploadRole, HTMLInputElement>> = {}
const uploadRoles = computed<UploadRole[]>(() => mode.value === 'standard_document'
  ? ['draft', 'standard'] : ['draft'])
const canSubmit = computed(() => uploadRoles.value.every(role =>
  selectedFiles.value[role] && !messages.value[role]))
const hasFiles = computed(() => !!selectedFiles.value.draft || !!selectedFiles.value.standard)

function setInput(role: UploadRole, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLInputElement) fileInputs[role] = element
  else delete fileInputs[role]
}

function clearRole(role: UploadRole) {
  selectedFiles.value[role] = null
  messages.value[role] = ''
  const input = fileInputs[role]
  if (input) input.value = ''
}

watch(mode, value => {
  if (value === 'knowledge_base') clearRole('standard')
})

function selectFile(role: UploadRole, event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] ?? null
  selectedFiles.value[role] = file
  messages.value[role] = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.docx')) {
    messages.value[role] = '目前只支持 .docx 格式。'
  } else if (file.size === 0) {
    messages.value[role] = '这个文件没有内容，请选择其他文件。'
  }
}

function clearFile() {
  clearRole('draft')
  clearRole('standard')
}

function submitFile() {
  const file = selectedFiles.value.draft
  if (!file || !canSubmit.value) return
  if (mode.value === 'standard_document') {
    const standardFile = selectedFiles.value.standard
    if (standardFile) emit('submit', { mode: mode.value, file, standardFile })
  } else {
    emit('submit', { mode: mode.value, file })
  }
}
</script>

<template>
  <section class="upload-panel" aria-labelledby="upload-title">
    <div class="panel-heading">
      <div>
        <div class="eyebrow"><span class="eyebrow-line"></span> START A REVIEW</div>
        <h2 id="upload-title">提交制度草稿</h2>
      </div>
      <span class="step-number">01 <span>/ 01</span></span>
    </div>

    <fieldset class="review-mode-field" :disabled="disabled">
      <legend>审核方式</legend>
      <div class="review-mode-options">
        <label><input v-model="mode" type="radio" value="knowledge_base" /> 知识库审核</label>
        <label><input v-model="mode" type="radio" value="standard_document" /> 标准文档对比</label>
      </div>
    </fieldset>
    <p class="upload-intro">{{ mode === 'standard_document'
      ? '上传制度草稿与标准文档，逐条对比并生成审核报告。'
      : '上传制度草稿，结合制度知识库逐条审核。' }}</p>

    <div v-for="role in uploadRoles" :key="role" class="review-file-field">
    <h3>{{ role === 'draft' ? '制度草稿' : '标准文档' }}</h3>

    <label class="dropzone" :class="{ 'dropzone-selected': selectedFiles[role], 'dropzone-invalid': messages[role] }">
      <input
        :ref="element => setInput(role, element)"
        :aria-label="role === 'draft' ? '制度草稿' : '标准文档'"
        class="visually-hidden"
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        :disabled="disabled"
        @change="selectFile(role, $event)"
      />
      <span class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 32 32" fill="none">
          <path d="M16 21V7m0 0-5 5m5-5 5 5M7 19v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
        </svg>
      </span>
      <span v-if="selectedFiles[role]" class="dropzone-copy">
        <strong class="selected-name">{{ selectedFiles[role]?.name }}</strong>
        <span>{{ ((selectedFiles[role]?.size ?? 0) / 1024 / 1024).toFixed(2) }} MB · 点击更换文件</span>
      </span>
      <span v-else class="dropzone-copy">
        <strong>{{ role === 'draft' ? '选择制度草稿' : '选择标准文档' }}</strong>
        <span>点击浏览文件 · 支持 DOCX 格式</span>
      </span>
      <span class="browse-button">浏览文件</span>
    </label>

    <p v-if="messages[role]" class="field-error" role="alert">{{ messages[role] }}</p>
    </div>
    <div class="upload-footnote">
      <span class="footnote-lock" aria-hidden="true">◈</span>
      当前版本不保留审核历史
    </div>

    <div class="upload-actions">
      <button v-if="hasFiles" class="button button-quiet" type="button" :disabled="disabled" @click="clearFile">
        清除
      </button>
      <button class="button button-primary" type="button" :disabled="!canSubmit || disabled" @click="submitFile">
        <span>{{ disabled ? '正在审核' : '开始审核' }}</span>
        <span class="button-arrow" aria-hidden="true">↗</span>
      </button>
    </div>
  </section>
</template>


<style scoped>
.review-mode-field { margin: 0 0 20px; padding: 0; border: 0; }
.review-mode-field legend { margin-bottom: 12px; font-weight: 600; }
.review-mode-options { display: flex; flex-wrap: wrap; gap: 16px 24px; }
.review-mode-options label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.review-mode-options input { accent-color: var(--accent, #cd5636); }
.review-file-field { margin-top: 20px; }
.review-file-field h3 { margin: 0 0 10px; font-size: 14px; }
</style>
