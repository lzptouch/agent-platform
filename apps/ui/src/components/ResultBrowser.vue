<!--
  F-UX-02 · 结果区「浏览器」视图。

  此前该视图是**占位**（「自动化任务页面/截图，后续接入」）——四视图里只有它没有数据源。
  现在数据源 = **浏览器类产物**（``artifacts.kind === 'browser'``）：
  自动化任务（Playwright 等）把页面截图登记为产物，并带上**来源页面 URL**。
-->
<template>
  <div class="browser-view">
    <div v-if="!pages.length" class="empty">
      <el-icon class="empty-icon"><Monitor /></el-icon>
      <div class="empty-title">暂无浏览器页面</div>
      <div class="empty-hint">
        自动化任务把页面截图登记为产物（<code>kind = "browser"</code>）后，这里会显示页面与地址。
      </div>
    </div>
    <div v-for="p in pages" :key="p.id" class="page">
      <div class="page-head">
        <span class="page-title" :title="p.title || ''">{{ p.title || '未命名页面' }}</span>
        <a
          v-if="p.url"
          class="page-url"
          :href="p.url"
          target="_blank"
          rel="noopener noreferrer"
        >{{ p.url }}</a>
        <span v-else class="page-url page-url--none">未记录地址</span>
      </div>
      <div class="page-shot">
        <img
          v-if="p.previewable && p.url"
          class="shot"
          :src="shotUrl(p)"
          :alt="p.title || '页面截图'"
          @error="onShotError(p)"
        />
        <div v-else class="shot shot--none">
          {{ p.previewable ? '无截图预览' : '该产物不支持预览' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Monitor } from '@element-plus/icons-vue'

import { runArtifacts, type ArtifactItem } from '@/api'

const props = defineProps<{ runId?: string | null }>()

/** 浏览器类产物（截图 + 来源 URL）。 */
const pages = ref<ArtifactItem[]>([])
const brokenShots = ref<Set<number>>(new Set())

/** 产物图片的可访问 URL（走后端文件接口，不直连磁盘）。 */
function shotUrl(a: ArtifactItem): string {
  return `/api/v1/files/${encodeURIComponent(a.path.split('/').pop() || a.path)}`
}

function onShotError(a: ArtifactItem): void {
  brokenShots.value = new Set([...brokenShots.value, a.id])
}

async function load(): Promise<void> {
  if (!props.runId) {
    pages.value = []
    return
  }
  try {
    const data = await runArtifacts(props.runId)
    pages.value = (data.items || []).filter(
      (a: ArtifactItem) => a.kind === 'browser',
    )
  } catch {
    pages.value = []
  }
}

let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  void load()
  timer = setInterval(() => void load(), 5000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

watch(() => props.runId, () => void load())
</script>

<style scoped>
.browser-view { display: flex; flex-direction: column; gap: 12px; }

.empty {
  padding: 24px;
  color: var(--text-faint);
  font-size: 13px;
  text-align: center;
}
.empty-icon { font-size: 22px; margin-bottom: 6px; }
.empty-title { color: var(--text-secondary); margin-bottom: 4px; }
.empty-hint { font-size: 12px; line-height: 1.6; }
.empty-hint code {
  background: var(--fill-quaternary, rgba(0, 0, 0, 0.04));
  padding: 1px 4px;
  border-radius: 3px;
}

.page {
  border: 1px solid var(--border-color, #e6e6e6);
  border-radius: 6px;
  overflow: hidden;
}
.page-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color, #e6e6e6);
}
.page-title { font-size: 13px; font-weight: 600; }
.page-url {
  font-size: 12px;
  color: var(--el-color-primary, #409eff);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.page-url--none { color: var(--text-faint); }
.page-shot { padding: 8px 10px; }
.shot { max-width: 100%; border-radius: 4px; display: block; }
.shot--none {
  color: var(--text-faint);
  font-size: 12px;
  padding: 16px;
  text-align: center;
  background: var(--fill-quaternary, rgba(0, 0, 0, 0.03));
  border-radius: 4px;
}
</style>
