<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import type { Gender } from './types'
const props = defineProps<{ id: string; modelValue: Gender | ''; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Gender | ''] }>()
const choices: { value: Gender | ''; label: string }[] = [
  { value: '', label: '未填写' }, { value: 'male', label: '男' }, { value: 'female', label: '女' },
  { value: 'other', label: '其他' }, { value: 'undisclosed', label: '不愿透露' },
]
const root = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>(), optionButtons = ref<HTMLButtonElement[]>([])
const open = ref(false), active = ref(0)
const selected = computed(() => choices.findIndex(choice => choice.value === props.modelValue))
async function focusOption(index: number) {
  active.value = (index + choices.length) % choices.length
  await nextTick()
  optionButtons.value[active.value]?.focus()
}
function close(restore = false) { open.value = false; if (restore) trigger.value?.focus() }
async function toggle() {
  if (props.disabled) return
  if (open.value) { close(true); return }
  open.value = true
  await focusOption(Math.max(0, selected.value))
}
function choose(value: Gender | '') { if (!props.disabled) { emit('update:modelValue', value); close(true) } }
function keydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true) }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const wasOpen = open.value
    open.value = true
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 :
      wasOpen ? active.value + (event.key === 'ArrowDown' ? 1 : -1) : Math.max(0, selected.value)
    void focusOption(index)
  }
}
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
function blur(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) close() }
watch(() => props.disabled, disabled => { if (disabled) close() })
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="profile-picker" @keydown="keydown" @focusout="blur">
    <button :id="id" ref="trigger" class="profile-picker-trigger" type="button" :disabled="disabled" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="`${id}-options`" :aria-labelledby="`${id}-label ${id}`" @click="toggle">
      <span>{{ choices[selected]?.label ?? '未填写' }}</span><ChevronDown :size="16" aria-hidden="true" />
    </button>
    <div v-if="open" :id="`${id}-options`" class="profile-picker-panel profile-gender-options" role="listbox" :aria-labelledby="`${id}-label`">
      <button v-for="choice in choices" :key="choice.value" ref="optionButtons" type="button" role="option" tabindex="-1" :aria-selected="choice.value === modelValue" :class="{ selected: choice.value === modelValue }" @click="choose(choice.value)">
        <span>{{ choice.label }}</span><Check v-if="choice.value === modelValue" :size="16" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
