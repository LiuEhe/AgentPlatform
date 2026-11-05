<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X } from '@lucide/vue'

const props = defineProps<{ file: File }>()
const emit = defineEmits<{ confirm: [file: File]; cancel: [] }>()
const dialog = ref<HTMLDialogElement>(), canvas = ref<HTMLCanvasElement>()
const zoom = ref(1), offsetX = ref(0), offsetY = ref(0)
const loading = ref(true), exporting = ref(false), error = ref('')
const canConfirm = computed(() => !loading.value && !exporting.value && !error.value)
let bitmap: ImageBitmap | undefined, sequence = 0, alive = true
let drag: { id: number; x: number; y: number } | undefined
const size = 512

function draw() {
  const context = canvas.value?.getContext('2d')
  if (!bitmap || !context) return
  const sourceSize = Math.min(bitmap.width, bitmap.height) / zoom.value
  const maxX = (bitmap.width / sourceSize - 1) * size / 2
  const maxY = (bitmap.height / sourceSize - 1) * size / 2
  offsetX.value = Math.max(-maxX, Math.min(maxX, offsetX.value))
  offsetY.value = Math.max(-maxY, Math.min(maxY, offsetY.value))
  const x = (bitmap.width - sourceSize) / 2 - offsetX.value / size * sourceSize
  const y = (bitmap.height - sourceSize) / 2 - offsetY.value / size * sourceSize
  context.clearRect(0, 0, size, size)
  context.drawImage(bitmap, x, y, sourceSize, sourceSize, 0, 0, size, size)
}
watch([zoom, offsetX, offsetY], draw)
watch(() => props.file, async file => {
  const current = ++sequence
  bitmap?.close(); bitmap = undefined
  loading.value = true; error.value = ''; zoom.value = 1; offsetX.value = 0; offsetY.value = 0
  try {
    const image = await createImageBitmap(file)
    if (!alive || current !== sequence) { image.close(); return }
    if (image.width > 8192 || image.height > 8192 || image.width * image.height > 16000000) {
      image.close(); throw new Error('图片尺寸过大，请选择较小的图片。')
    }
    bitmap = image
    await nextTick()
    if (alive && current === sequence) draw()
  } catch (reason) {
    if (alive && current === sequence) error.value = reason instanceof Error && reason.message.startsWith('图片尺寸') ? reason.message : '图片无法打开，请重新选择。'
  } finally { if (alive && current === sequence) loading.value = false }
}, { immediate: true })
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => { alive = false; sequence++; bitmap?.close(); bitmap = undefined; dialog.value?.close() })
function cancel() { sequence++; emit('cancel') }
function startDrag(event: PointerEvent) {
  if (!canConfirm.value) return
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY }
  canvas.value?.setPointerCapture(event.pointerId)
}
function moveDrag(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId || !canvas.value) return
  const scale = size / canvas.value.getBoundingClientRect().width
  offsetX.value += (event.clientX - drag.x) * scale
  offsetY.value += (event.clientY - drag.y) * scale
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY }
}
function stopDrag() { drag = undefined }
function moveWithKeys(event: KeyboardEvent) {
  if (!canConfirm.value) return
  const steps: Record<string, [number, number]> = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] }
  const step = steps[event.key]
  if (step) { event.preventDefault(); offsetX.value += step[0]; offsetY.value += step[1] }
}
async function confirm() {
  if (!canConfirm.value || !canvas.value) return
  const current = sequence
  exporting.value = true
  try {
    draw()
    const blob = await new Promise<Blob | null>(resolve => canvas.value!.toBlob(resolve, 'image/png'))
    if (!alive || current !== sequence) return
    if (!blob) throw new Error('图片处理失败，请重新选择。')
    emit('confirm', new File([blob], 'avatar.png', { type: 'image/png' }))
  } catch { if (alive && current === sequence) error.value = '图片处理失败，请重新选择。' }
  finally { if (alive && current === sequence) exporting.value = false }
}
</script>
<template>
  <dialog ref="dialog" class="avatar-crop-dialog" aria-labelledby="avatar-crop-title" @cancel.prevent="cancel">
    <div class="account-dialog-heading"><div><h2 id="avatar-crop-title">裁剪头像</h2><p>拖动图片调整位置</p></div><button type="button" class="icon-button" aria-label="取消裁剪头像" @click="cancel"><X :size="20" /></button></div>
    <div class="avatar-crop-body">
      <p v-if="loading" role="status">正在读取图片…</p>
      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
      <canvas ref="canvas" width="512" height="512" tabindex="0" aria-label="头像裁剪预览，可拖动或使用方向键调整位置" :aria-busy="loading || exporting" @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="stopDrag" @pointercancel="stopDrag" @lostpointercapture="stopDrag" @keydown="moveWithKeys"></canvas>
      <label class="avatar-crop-zoom" for="avatar-crop-zoom">缩放<input id="avatar-crop-zoom" v-model.number="zoom" type="range" min="1" max="3" step="0.01" :disabled="!canConfirm"></label>
    </div>
    <div class="account-dialog-actions"><button type="button" class="button" @click="cancel">取消</button><button id="avatar-crop-confirm" type="button" class="button account-primary" :disabled="!canConfirm" @click="confirm">{{ exporting ? '处理中…' : '确认' }}</button></div>
  </dialog>
</template>
