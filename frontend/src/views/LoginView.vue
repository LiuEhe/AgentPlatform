<script setup lang="ts">
import LoginForm from '../features/auth/LoginForm.vue'
</script>
<template>
  <section class="auth-split">
    <div class="auth-intro"><div class="eyebrow">连接每一次灵感与实践</div><h1>在这里，<br>让工作更有章法。</h1><div class="auth-rule"></div><p>一个连接想法、材料与行动的智能工作空间。</p><div class="auth-paper" aria-hidden="true"><b>工作手记</b><i></i><i></i><i></i><small>想法 · 材料 · 进展</small></div><div class="auth-traits"><span>专属工作空间</span><span>更连贯的体验</span></div></div>
    <LoginForm />
  </section>
</template>
