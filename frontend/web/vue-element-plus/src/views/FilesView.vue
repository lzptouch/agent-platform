<template>
  <div class="files-view">
    <h2>产出文件</h2>
    <p class="hint">列出后端 <code>data/outputs/</code> 下的文件。聊天日志 <code>chat_log_*.json</code> 会自动分组到"日志"。</p>

    <div class="actions">
      <el-button @click="refresh" :loading="loading">刷新</el-button>
      <el-upload :http-request="uploadFile" :show-file-list="false" :accept="acceptAttr">
        <el-button type="primary">上传文件</el-button>
      </el-upload>
    </div>

    <div v-if="!items.length && !loading" class="empty">暂无文件</div>

    <el-tabs v-model="activeTab" v-else>
      <el-tab-pane :label="`全部 (${items.length})`" name="all" />
      <el-tab-pane :label="`图片 (${images.length})`" name="image" />
      <el-tab-pane :label="`报告与文档 (${docs.length})`" name="doc" />
      <el-tab-pane :label="`聊天日志 (${logs.length})`" name="log" />
      <el-tab-pane :label="`其他 (${others.length})`" name="other" />
    </el-tabs>

    <div v-if="filtered.length" class="grid">
      <el-card v-for="f in filtered" :key="f.name" class="card" shadow="hover">
        <div v-if="f.is_image" class="img-wrap">
          <a :href="fileUrl(f.name)" target="_blank">
            <img :src="fileUrl(f.name)" :alt="f.name" loading="lazy" />
          </a>
        </div>
        <div v-else class="file-icon">📄</div>
        <div class="meta">
          <div class="name" :title="f.name">{{ f.name }}</div>
          <div class="sub">{{ formatSize(f.size) }}</div>
        </div>
        <div class="ops">
          <a class="op" :href="fileUrl(f.name)" target="_blank">下载</a>
          <el-popconfirm title="确认删除？" @confirm="remove(f.name)">
            <template #reference><span class="op danger">删除</span></template>
          </el-popconfirm>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'
import { filesList, deleteFile, filesUpload } from '@/api'
import { ALLOWED_UPLOAD_EXTENSIONS, checkUploadFile } from '@/api/upload-policy'
import type { FileItem } from '@/api/types'

const items = ref<FileItem[]>([])
const loading = ref(false)
const activeTab = ref<'all' | 'image' | 'doc' | 'log' | 'other'>('all')

// 文件选择器的 accept 提示（与后端白名单同口径）
const acceptAttr = ALLOWED_UPLOAD_EXTENSIONS.map((ext) => `.${ext}`).join(',')

onMounted(() => refresh())

async function refresh() {
  loading.value = true
  try { items.value = (await filesList()).files }
  finally { loading.value = false }
}

function fileUrl(name: string) { return `/api/v1/files/${encodeURIComponent(name)}` }
function formatSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

const images = computed(() => items.value.filter(f => f.is_image))
const docs = computed(() => items.value.filter(f => !f.is_image && /\.(md|pdf|txt|json|csv|html?|xml)$/i.test(f.name) && !/^chat_log_/.test(f.name)))
const logs = computed(() => items.value.filter(f => /^chat_log_/.test(f.name)))
const others = computed(() => items.value.filter(f => !f.is_image && !/\.(md|pdf|txt|json|csv|html?|xml)$/i.test(f.name) && !/^chat_log_/.test(f.name)))
const filtered = computed(() => {
  switch (activeTab.value) {
    case 'image': return images.value
    case 'doc': return docs.value
    case 'log': return logs.value
    case 'other': return others.value
    default: return items.value
  }
})

async function remove(name: string) {
  try { await deleteFile(name); await refresh(); ElMessage.success('已删除') }
  catch (e: unknown) { ElMessage.error(`删除失败：${(e as Error).message}`) }
}

async function uploadFile(opts: UploadRequestOptions) {
  // 上传前预检（大小 + 类型）：先给出可读提示，避免把明显不合规的文件发到后端
  const reason = checkUploadFile(opts.file)
  if (reason) {
    ElMessage.error(reason)
    return
  }
  const fd = new FormData()
  fd.append('file', opts.file)
  try {
    await filesUpload(fd)
    await refresh()
    ElMessage.success(`已上传`)
  } catch (e: unknown) {
    ElMessage.error(`上传失败：${(e as Error).message}`)
  }
}
</script>

<style scoped>
.files-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.empty { color: var(--text-dim); padding: 32px; text-align: center; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.card { padding: 0; }
.img-wrap { width: 100%; height: 140px; overflow: hidden; background: var(--bg-code); display: grid; place-items: center; }
.img-wrap img { max-width: 100%; max-height: 140px; }
.file-icon { width: 100%; height: 140px; display: grid; place-items: center; font-size: 48px; background: var(--bg-sidebar); }
.meta { padding: 8px 10px; }
.meta .name { font-weight: 500; font-size: 13px; word-break: break-all; }
.meta .sub { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.ops { display: flex; gap: 12px; padding: 0 10px 10px; font-size: 12px; }
.ops .op { color: var(--accent); cursor: pointer; }
.ops .op:hover { text-decoration: underline; }
.ops .op.danger { color: var(--red); }
</style>