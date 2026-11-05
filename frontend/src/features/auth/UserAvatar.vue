<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { getAvatar } from '../../api/users'
import { useAuth } from './useAuth'
const props = defineProps<{ hasAvatar: boolean; userId?: string; revision: string | number; alt: string }>()
const auth = useAuth(), source = ref('')
let sequence = 0, controller: AbortController | undefined
function clear() {
  controller?.abort()
  if (source.value) URL.revokeObjectURL(source.value)
  source.value = ''
}
watch([() => props.hasAvatar, () => props.userId, () => props.revision, () => auth.epoch.value, () => auth.phase.value], async () => {
  const current = ++sequence, ticket = auth.capture()
  clear()
  if (!props.hasAvatar || !ticket) return
  controller = new AbortController()
  try {
    const blob = await getAvatar(props.userId, controller.signal)
    if (current === sequence && auth.isCurrent(ticket)) source.value = URL.createObjectURL(blob)
  } catch { /* Missing or unavailable avatars use the default initial. */ }
}, { immediate: true })
onBeforeUnmount(() => { sequence++; clear() })
</script>
<template>
  <img v-if="source" class="user-avatar" :src="source" :alt="alt" width="40" height="40">
  <span v-else class="user-avatar user-avatar-default" role="img" :aria-label="alt">{{ alt.slice(0, 1) || '用' }}</span>
</template>
