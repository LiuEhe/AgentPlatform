<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{
  submit: [file: File]
}>()

const selectedFile = ref<File | null>(null)
const validationMessage = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  selectedFile.value = file
  validationMessage.value = ''

  if (!file) return
  if (!file.name.toLowerCase().endsWith('.docx')) {
    validationMessage.value = '目前只支持 .docx 格式的制度草稿。'
    return
  }
  if (file.size === 0) {
    validationMessage.value = '这个文件没有内容，请选择其他文件。'
  }
}

function clearFile() {
  selectedFile.value = null
  validationMessage.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function submitFile() {
  const file = selectedFile.value
  if (!file || validationMessage.value) return
  emit('submit', file)
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

    <p class="upload-intro">上传 Word 文档，智能体将为你梳理条款问题并生成审核报告。</p>

    <label class="dropzone" :class="{ 'dropzone-selected': selectedFile, 'dropzone-invalid': validationMessage }">
      <input
        ref="fileInput"
        class="visually-hidden"
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        :disabled="disabled"
        @change="selectFile"
      />
      <span class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 32 32" fill="none">
          <path d="M16 21V7m0 0-5 5m5-5 5 5M7 19v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
        </svg>
      </span>
      <span v-if="selectedFile" class="dropzone-copy">
        <strong class="selected-name">{{ selectedFile.name }}</strong>
        <span>{{ (selectedFile.size / 1024 / 1024).toFixed(2) }} MB · 点击更换文件</span>
      </span>
      <span v-else class="dropzone-copy">
        <strong>选择一份制度草稿</strong>
        <span>点击浏览文件 · 支持 DOCX 格式</span>
      </span>
      <span class="browse-button">浏览文件</span>
    </label>

    <p v-if="validationMessage" class="field-error" role="alert">{{ validationMessage }}</p>
    <div class="upload-footnote">
      <span class="footnote-lock" aria-hidden="true">◈</span>
      当前版本不保留审核历史
    </div>

    <div class="upload-actions">
      <button v-if="selectedFile" class="button button-quiet" type="button" :disabled="disabled" @click="clearFile">
        清除
      </button>
      <button class="button button-primary" type="button" :disabled="!selectedFile || !!validationMessage || disabled" @click="submitFile">
        <span>{{ disabled ? '正在审核' : '开始审核' }}</span>
        <span class="button-arrow" aria-hidden="true">↗</span>
      </button>
    </div>
  </section>
</template>
