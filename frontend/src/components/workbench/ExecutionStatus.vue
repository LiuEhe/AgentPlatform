<script setup lang="ts">
import { CircleAlert, CircleCheck, LoaderCircle } from '@lucide/vue'
import type { ReviewStatus } from '../../features/institution-review/types'
defineProps<{ status: ReviewStatus; message?: string }>()
</script>
<template>
  <div v-if="status !== 'idle'" class="execution-status" :class="`status-${status}`" :role="status === 'error' ? 'alert' : 'status'" aria-live="polite">
    <LoaderCircle v-if="status === 'submitting'" class="spin" :size="20" aria-hidden="true" />
    <CircleCheck v-else-if="status === 'success'" :size="20" aria-hidden="true" />
    <CircleAlert v-else :size="20" aria-hidden="true" /><span>{{ message }}</span>
  </div>
</template>
