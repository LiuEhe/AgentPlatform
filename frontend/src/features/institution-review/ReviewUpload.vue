<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BookOpen, Check, CircleAlert, CircleCheck, Files } from '@lucide/vue'
import ReviewFileInput from './ReviewFileInput.vue'
import type { ReviewMode, ReviewSubmission } from './types'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ submit: [submission: ReviewSubmission] }>()
type Role = 'draft' | 'standard'
const mode = ref<ReviewMode>('standard_document')
const selectedFiles = ref<Record<Role, File | null>>({ draft: null, standard: null })
const errors = ref<Record<Role, string>>({ draft: '', standard: '' })
const ready = computed(() => Boolean(selectedFiles.value.draft && !errors.value.draft &&
  (mode.value === 'knowledge_base' || (selectedFiles.value.standard && !errors.value.standard))))
const missing = computed(() => !selectedFiles.value.draft ? '请先上传草稿' : '请先上传标准文档')
watch(mode, value => { if (value === 'knowledge_base') select('standard', null) })
function select(role: Role, file: File | null) {
  if (props.disabled) return
  selectedFiles.value[role] = file
  errors.value[role] = !file ? '' : !file.name.toLowerCase().endsWith('.docx')
    ? '目前只支持 .docx 格式。' : file.size === 0 ? '这个文件没有内容，请选择其他文件。' : ''
}
function submit() {
  if (props.disabled || !ready.value || !selectedFiles.value.draft) return
  const file = selectedFiles.value.draft
  if (mode.value === 'standard_document' && selectedFiles.value.standard) {
    emit('submit', { mode: mode.value, file, standardFile: selectedFiles.value.standard })
  } else if (mode.value === 'knowledge_base') emit('submit', { mode: mode.value, file })
}
</script>

<template>
  <div class="review-grid">
    <div>
      <fieldset class="form-card" :disabled="disabled">
        <legend class="visually-hidden">上传待审草稿</legend>
        <h2 class="form-title"><span class="step">1</span>上传待审草稿</h2>
        <ReviewFileInput id="review-draft" label="待审草稿" :file="selectedFiles.draft" :error="errors.draft" :disabled="disabled" @select="select('draft', $event)" />
        <p class="form-note">{{ selectedFiles.draft ? '提交前可以移除或替换材料。' : '选择你希望审核的制度草稿。' }}</p>
      </fieldset>
      <fieldset class="form-card" :disabled="disabled">
        <legend class="visually-hidden">选择审核依据</legend>
        <h2 class="form-title"><span class="step">2</span>选择审核依据</h2>
        <div class="mode-options">
          <label class="mode-card" :class="{ active: mode === 'standard_document' }">
            <input v-model="mode" class="visually-hidden" type="radio" name="review-mode" value="standard_document" />
            <Files :size="22" aria-hidden="true" /><span><strong>上传标准文档</strong><small>与指定的标准全文对照</small></span>
          </label>
          <label class="mode-card" :class="{ active: mode === 'knowledge_base' }">
            <input v-model="mode" class="visually-hidden" type="radio" name="review-mode" value="knowledge_base" />
            <BookOpen :size="22" aria-hidden="true" /><span><strong>制度知识库</strong><small>按条款检索相关依据</small></span>
          </label>
        </div>
        <ReviewFileInput v-if="mode === 'standard_document'" id="review-standard" label="标准文档" :file="selectedFiles.standard" :error="errors.standard" :disabled="disabled" @select="select('standard', $event)" />
        <div v-else class="knowledge-note"><BookOpen :size="22" aria-hidden="true" /><div><strong>使用制度知识库</strong><p>由服务端检索相关制度作为依据，需要知识库配置可用。</p></div></div>
        <p v-if="!ready && !errors.draft && !errors.standard" class="inline-note"><CircleAlert :size="17" aria-hidden="true" />{{ !selectedFiles.draft ? '先添加待审草稿，再开始审核。' : '还差一份标准文档，上传后即可开始。' }}</p>
      </fieldset>
      <div class="form-actions">
        <span class="muted row small"><CircleCheck :size="18" aria-hidden="true" />提交前可随时替换材料</span>
        <button class="button button-primary" type="button" :disabled="!ready || disabled" @click="submit">{{ disabled ? '正在审核…' : ready ? '开始审核' : missing }}</button>
      </div>
    </div>
    <aside class="review-summary">
      <div class="summary-card">
        <h2>本次审核</h2><dl>
          <div><dt>待审材料</dt><dd>{{ selectedFiles.draft?.name ?? '等待上传' }}</dd></div>
          <div><dt>审核方式</dt><dd>{{ mode === 'standard_document' ? '标准文档对照' : '知识库审核' }}</dd></div>
          <div><dt>对照依据</dt><dd>{{ mode === 'knowledge_base' ? '制度知识库' : selectedFiles.standard?.name ?? '等待上传' }}</dd></div>
        </dl>
        <p class="summary-note"><component :is="ready ? CircleCheck : CircleAlert" :size="17" aria-hidden="true" />{{ ready ? '材料已齐全，可以开始审核' : '材料齐全后，开始审核' }}</p>
      </div>
      <div class="output-note"><h2>你将得到</h2><ul><li v-for="item in ['审核简述与主要结论', '冲突检测与相关依据', '全文术语检查', '可操作的修改建议']" :key="item"><Check :size="17" aria-hidden="true" />{{ item }}</li></ul><p>报告支持下载为 Word，便于后续修订与流转。</p></div>
    </aside>
  </div>
</template>
