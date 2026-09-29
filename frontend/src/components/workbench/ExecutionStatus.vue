<script setup lang="ts">
import type { ReviewStatus } from '../../features/institution-review/types'

defineProps<{
  status: ReviewStatus
  message?: string
}>()
</script>

<template>
  <div v-if="status !== 'idle'" class="execution-status" :class="`status-${status}`" role="status" aria-live="polite">
    <span v-if="status === 'submitting'" class="spinner" aria-hidden="true"></span>
    <span v-else class="status-symbol" aria-hidden="true">{{ status === 'success' ? '✓' : '!' }}</span>
    <span>{{ message }}</span>
  </div>
</template>
