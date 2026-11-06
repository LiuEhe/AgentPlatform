<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from '@lucide/vue'
import { createProfileDate, formatProfileDate, parseProfileDate } from './profileDates'
const props = defineProps<{ id: string; modelValue: string; max: string; disabled?: boolean; invalid?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; focus: [] }>()
const root = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>(), panel = ref<HTMLElement>(), period = ref<HTMLButtonElement>()
const dayButtons = ref<HTMLButtonElement[]>([])
const open = ref(false), mode = ref<'days' | 'years' | 'months'>('days')
const year = ref(2000), month = ref(1), focused = ref('')
const maxYear = computed(() => Number(props.max.slice(0, 4)))
const firstYear = ref(1993)
const years = computed(() => Array.from({ length: 12 }, (_, i) => firstYear.value + i))
const days = computed(() => {
  const first = createProfileDate(year.value, month.value, 1)
  const offset = (first.getUTCDay() + 6) % 7
  return Array.from({ length: 42 }, (_, i) => {
    const date = createProfileDate(year.value, month.value, i + 1 - offset)
    const value = formatProfileDate(date)
    return { value, label: date.getUTCDate(), other: date.getUTCMonth() + 1 !== month.value,
      disabled: !parseProfileDate(value) || value > props.max }
  })
})
const heading = computed(() => mode.value === 'years' ? `${firstYear.value} – ${firstYear.value + 11}` :
  mode.value === 'months' ? `${year.value} 年` : `${year.value} 年 ${month.value} 月`)
const previousDisabled = computed(() => mode.value === 'years' ? firstYear.value <= 1 : mode.value === 'months' ? year.value <= 1 : year.value === 1 && month.value === 1)
const nextDisabled = computed(() => mode.value === 'years' ? firstYear.value + 12 > maxYear.value : mode.value === 'months' ? year.value >= maxYear.value : `${String(year.value).padStart(4, '0')}-${String(month.value).padStart(2, '0')}` >= props.max.slice(0, 7))
function close(restore = false) { open.value = false; if (restore) trigger.value?.focus() }
async function focusDay() {
  await nextTick()
  dayButtons.value.find(button => button.getAttribute('data-date') === focused.value)?.focus()
}
function view(date: Date) { year.value = date.getUTCFullYear(); month.value = date.getUTCMonth() + 1; focused.value = formatProfileDate(date) }
async function toggle() {
  if (props.disabled) return
  if (open.value) { close(true); return }
  emit('focus')
  await nextTick()
  const selected = parseProfileDate(props.modelValue)
  view(selected && props.modelValue <= props.max ? selected : parseProfileDate(props.max)!)
  mode.value = 'days'; open.value = true
  await focusDay()
  panel.value?.scrollIntoView({ block: 'nearest' })
}
function choose(value: string) {
  if (props.disabled || (value && (!parseProfileDate(value) || value > props.max))) return
  emit('update:modelValue', value); close(true)
}
async function chooseToday() { emit('focus'); await nextTick(); choose(props.max) }
function shift(direction: number) {
  if ((direction < 0 && previousDisabled.value) || (direction > 0 && nextDisabled.value)) return
  if (mode.value === 'years') firstYear.value += direction * 12
  else if (mode.value === 'months') year.value += direction
  else {
    const date = createProfileDate(year.value, month.value + direction, 1)
    view(date)
  }
}
function quickSelect() {
  period.value?.focus()
  firstYear.value = Math.floor((year.value - 1) / 12) * 12 + 1
  mode.value = 'years'
}
function chooseYear(value: number) { period.value?.focus(); year.value = value; mode.value = 'months' }
async function chooseMonth(value: number) {
  period.value?.focus()
  month.value = value; mode.value = 'days'
  focused.value = `${year.value.toString().padStart(4, '0')}-${String(value).padStart(2, '0')}-01`
  await focusDay()
}
function monthDisabled(value: number) { return year.value === maxYear.value && value > Number(props.max.slice(5, 7)) }
async function dayKey(event: KeyboardEvent, value: string) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) return
  event.preventDefault()
  const date = parseProfileDate(value)!
  const weekday = (date.getUTCDay() + 6) % 7
  const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7, Home: -weekday, End: 6 - weekday }
  let next: Date
  if (event.key === 'PageUp' || event.key === 'PageDown') {
    const delta = (event.key === 'PageUp' ? -1 : 1) * (event.shiftKey ? 12 : 1)
    const last = createProfileDate(date.getUTCFullYear(), date.getUTCMonth() + 2 + delta, 0).getUTCDate()
    next = createProfileDate(date.getUTCFullYear(), date.getUTCMonth() + 1 + delta, Math.min(date.getUTCDate(), last))
  } else next = createProfileDate(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate() + offsets[event.key]!)
  const formatted = formatProfileDate(next)
  if (formatted < '0001-01-01') next = createProfileDate(1, 1, 1)
  else if (formatted > props.max) next = parseProfileDate(props.max)!
  view(next); await focusDay()
}
function keydown(event: KeyboardEvent) { if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true) } }
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
function blur(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) close() }
watch(() => props.disabled, disabled => { if (disabled) close() })
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="profile-picker" @keydown="keydown" @focusout="blur">
    <div class="profile-date-input" :class="{ invalid }">
      <input :id="id" :value="modelValue" type="text" autocomplete="bday" placeholder="YYYY-MM-DD" maxlength="10" :disabled="disabled" :aria-invalid="invalid" :aria-describedby="invalid ? `${id}-error` : undefined" @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)" @focus="emit('focus')" @keydown.down.prevent="toggle">
      <button ref="trigger" class="profile-calendar-trigger" type="button" aria-label="选择生日" aria-haspopup="dialog" :aria-expanded="open" :aria-controls="`${id}-calendar`" :disabled="disabled" @click="toggle"><CalendarDays :size="16" aria-hidden="true" /></button>
    </div>
    <div v-if="open" :id="`${id}-calendar`" ref="panel" class="profile-picker-panel profile-calendar" role="dialog" aria-label="选择生日">
      <div class="profile-calendar-heading">
        <button class="profile-calendar-arrow" type="button" :aria-label="mode === 'days' ? '上个月' : '上一组'" :disabled="previousDisabled" @click="shift(-1)"><ChevronLeft :size="17" aria-hidden="true" /></button>
        <button ref="period" class="profile-calendar-period" type="button" aria-label="快速选择年月" @click="quickSelect">{{ heading }}<ChevronDown :size="13" aria-hidden="true" /></button>
        <button class="profile-calendar-arrow" type="button" :aria-label="mode === 'days' ? '下个月' : '下一组'" :disabled="nextDisabled" @click="shift(1)"><ChevronRight :size="17" aria-hidden="true" /></button>
      </div>
      <template v-if="mode === 'days'">
        <div class="profile-calendar-week" aria-hidden="true"><span v-for="day in ['一', '二', '三', '四', '五', '六', '日']" :key="day">{{ day }}</span></div>
        <div class="profile-calendar-days">
          <button v-for="day in days" :key="day.value" ref="dayButtons" type="button" :data-date="day.value" :aria-label="day.value" :aria-pressed="day.value === modelValue" :aria-current="day.value === max ? 'date' : undefined" :class="{ 'other-month': day.other, selected: day.value === modelValue }" :disabled="day.disabled" :tabindex="day.value === focused ? 0 : -1" @focus="focused = day.value" @click="choose(day.value)" @keydown="dayKey($event, day.value)">{{ day.label }}</button>
        </div>
      </template>
      <div v-else-if="mode === 'years'" class="profile-calendar-periods" aria-label="选择年份"><button v-for="value in years" :key="value" type="button" :data-year="value" :disabled="value > maxYear" :class="{ selected: value === year }" @click="chooseYear(value)">{{ value }} 年</button></div>
      <div v-else class="profile-calendar-periods" aria-label="选择月份"><button v-for="value in 12" :key="value" type="button" :data-month="value" :disabled="monthDisabled(value)" :class="{ selected: value === month }" @click="chooseMonth(value)">{{ value }} 月</button></div>
      <div class="profile-calendar-footer"><button type="button" @click="choose('')">清除</button><button type="button" @click="chooseToday">今天</button></div>
    </div>
  </div>
</template>
