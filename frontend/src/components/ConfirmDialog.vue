<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { X } from '@lucide/vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  id?: string
  subject?: string
  subjectLabel?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'default' | 'danger'
  busy?: boolean
  confirmDisabled?: boolean
  returnFocus?: HTMLElement | null
}>(), { confirmLabel: '确认', cancelLabel: '取消', variant: 'default', busy: false, confirmDisabled: false })
const emit = defineEmits<{ 'update:open': [value: boolean]; confirm: [] }>()
const generatedId = useId()
const dialogId = computed(() => props.id ?? generatedId)
const dialog = ref<HTMLDialogElement>()
const cancelButton = ref<HTMLButtonElement>()
let trigger: HTMLElement | null = null
let focusPending = false
let confirmed = false

function restoreFocus() {
  if (!focusPending) return
  focusPending = false
  const target = props.returnFocus ?? trigger
  if (target?.isConnected) target.focus()
  trigger = null
}
function syncOpen() {
  const element = dialog.value
  if (!element) return
  if (props.open && !element.open) {
    trigger = document.activeElement as HTMLElement | null
    focusPending = true
    confirmed = false
    element.showModal()
    cancelButton.value?.focus()
  } else if (!props.open && element.open) element.close()
}
function cancel() { if (!props.busy) emit('update:open', false) }
function confirm() {
  if (!props.open || props.busy || props.confirmDisabled || confirmed) return
  confirmed = true
  emit('confirm')
}
function closed() {
  if (dialog.value?.open) return
  if (props.open) emit('update:open', false)
  restoreFocus()
}
watch(() => props.open, syncOpen, { flush: 'post' })
watch(() => props.busy, busy => { if (!busy) confirmed = false })
onMounted(syncOpen)
onBeforeUnmount(() => { dialog.value?.close(); restoreFocus() })
</script>

<template>
  <dialog ref="dialog" class="app-confirm" :aria-labelledby="`${dialogId}-title`" :aria-describedby="`${dialogId}-description`" :aria-busy="busy" @cancel.prevent="cancel" @close="closed">
    <div class="confirm-heading">
      <h2 :id="`${dialogId}-title`">{{ title }}</h2>
      <button :id="`${dialogId}-close`" class="confirm-close" type="button" :aria-label="cancelLabel" :disabled="busy" @click="cancel"><X :size="18" aria-hidden="true" /></button>
    </div>
    <div :id="`${dialogId}-description`" class="confirm-body">
      <div v-if="subject !== undefined" class="confirm-subject"><small v-if="subjectLabel">{{ subjectLabel }}</small><span>{{ subject }}</span></div>
      <slot />
    </div>
    <div class="confirm-actions">
      <button :id="`${dialogId}-cancel`" ref="cancelButton" class="button" type="button" autofocus :disabled="busy" @click="cancel">{{ cancelLabel }}</button>
      <button :id="`${dialogId}-confirm`" class="button confirm-action" :class="{ 'confirm-danger': variant === 'danger' }" type="button" :disabled="busy || confirmDisabled" @click="confirm">{{ confirmLabel }}</button>
    </div>
  </dialog>
</template>

<style scoped>
.app-confirm { width: min(440px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); margin: auto; padding: 0; overflow-y: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--canvas); color: var(--ink); box-shadow: 0 18px 44px #29272226; }
.app-confirm::backdrop { background: #29272255; }
.confirm-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 24px 24px 16px; }
.confirm-heading h2 { margin: 0; font-size: 18px; font-weight: 600; line-height: 28px; overflow-wrap: anywhere; }
.confirm-close { display: grid; place-items: center; width: 28px; height: 28px; flex-shrink: 0; padding: 0; border-radius: 4px; color: var(--muted); }
.confirm-close:hover:not(:disabled) { background: var(--sidebar); }
.confirm-body { padding: 0 24px 24px; color: var(--muted); font-size: 14px; line-height: 24px; overflow-wrap: anywhere; }
.confirm-body :deep(p + p) { margin-top: 14px; }
.confirm-subject { display: flex; align-items: baseline; gap: 14px; min-height: 44px; margin-bottom: 14px; padding: 11px 14px; border-radius: 6px; background: var(--sidebar); color: var(--ink); }
.confirm-subject small { flex-shrink: 0; color: var(--muted); font-size: 12px; }
.confirm-subject span { min-width: 0; white-space: pre-wrap; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 24px; border-top: 1px solid var(--border); }
.confirm-actions .button { min-width: 64px; min-height: 38px; padding: 0 16px; border-radius: 6px; font-size: 13px; }
.confirm-action { background: var(--ink); border-color: var(--ink); color: var(--canvas); }
.confirm-action:hover:not(:disabled) { background: #474740; border-color: #474740; }
.confirm-danger { background: var(--error); border-color: var(--error); color: white; }
.confirm-danger:hover:not(:disabled) { background: #8d342a; border-color: #8d342a; }
@media (max-width: 500px) {
  .confirm-heading { padding: 20px 20px 16px; }
  .confirm-body { padding: 0 20px 20px; }
  .confirm-actions { padding: 16px 20px; }
  .confirm-actions .button { min-height: 40px; }
}
</style>
