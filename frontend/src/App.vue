<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="AgentPlatform 首页">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75L16 3.5Z" />
            <path d="M11 18.5 16 10l5 8.5M12.8 15.5h6.4M12.5 21h7" />
          </svg>
        </span>
        <span class="brand-name">Agent<span>Platform</span></span>
      </RouterLink>

      <nav class="top-nav" aria-label="主导航">
        <RouterLink to="/" class="nav-link">智能体</RouterLink>
        <span class="nav-link nav-link-muted">智能体工作空间</span>
      </nav>

      <div class="topbar-meta">
        <span class="status-dot" aria-hidden="true"></span>
        <span>智能体工作空间</span>
      </div>
    </header>

    <main class="main-content">
      <RouterView />
    </main>

    <footer class="site-footer">
      <span>AgentPlatform · 智能体应用工作空间</span>
      <span class="footer-note"><span class="footer-sparkle">✳</span> 让专业流程，更进一步</span>
    </footer>
  </div>
</template>
