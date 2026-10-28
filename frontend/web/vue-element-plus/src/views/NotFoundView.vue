<template>
  <div class="not-found">
    <div class="code">404</div>
    <h2>页面不存在</h2>
    <p class="path">{{ route.fullPath }}</p>
    <p class="hint">该地址没有对应的界面。可能是链接过期或功能尚未开放。</p>
    <el-button type="primary" @click="goHome">回到工作台</el-button>
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

function goHome(): void {
  void router.push('/workspace')
}
</script>

<style scoped>
.not-found { padding: 64px 24px; text-align: center; color: var(--text-dim); }
.code { font-size: 56px; font-weight: 700; color: var(--text-faint); line-height: 1; }
h2 { margin: 12px 0 4px; color: var(--text); }
.path { font-family: ui-monospace, monospace; font-size: 13px; color: var(--text-faint); }
.hint { margin: 6px 0 20px; font-size: 13px; }
</style>
