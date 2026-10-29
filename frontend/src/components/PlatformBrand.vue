<script setup lang="ts">
import { PanelsTopLeft } from '@lucide/vue'
import { RouterLink } from 'vue-router'
</script>

<template>
  <RouterLink class="brand" to="/" aria-label="AgentPlatform 首页">
    <PanelsTopLeft :size="25" :stroke-width="1.75" aria-hidden="true" />
    <span>AgentPlatform</span>
  </RouterLink>
</template>
