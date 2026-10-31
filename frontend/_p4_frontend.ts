/**
 * P4-13（挂载 WorkspacePicker）+ P4-04（上传策略运行时拉取）。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = join(process.cwd(), 'src')

function patch(rel: string, pairs: [string, string][], label: string): void {
  const path = join(ROOT, rel)
  let t = readFileSync(path, 'utf-8')
  for (const [a, b] of pairs) {
    if (!t.includes(a)) throw new Error(`❌ ${label}: 锚点未命中 ${a.slice(0, 70)}`)
    t = t.replace(a, b)
  }
  writeFileSync(path, t, 'utf-8')
  console.log(`✅ ${label}`)
}

// ============================================================ P4-04 上传策略运行时拉取
patch('api/upload-policy.ts', [[
  `/** 单文件大小上限（50 MB，与后端 \`upload_max_file_bytes\` 默认值一致） */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024`,
  `/** 单文件大小上限（50 MB，与后端 \`upload_max_file_bytes\` 默认值一致） */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/**
 * **P4-04**：上传白名单此前有**三份**（本文件、后端内置清单、环境变量覆盖）→
 * 前端拦下的扩展名后端可能放行（或反之）。
 *
 * 现在白名单以**后端为准**：启动时拉取 \`GET /api/v1/files/policy\`，
 * 拉取失败则回退到本文件的静态兜底值。
 */

/** 后端当前生效的上传策略（未拉取时为 null → 用静态兜底） */
let runtimePolicy: {
  extensions: string[]
  max_file_bytes: number
} | null = null

/** 拉取后端当前生效的上传策略（带本地兜底，失败不抛错）。 */
export async function loadUploadPolicy(): Promise<void> {
  try {
    const { get } = await import('@/api/client')
    const data = await get<{ extensions: string[]; max_file_bytes: number }>(
      '/api/v1/files/policy',
    )
    if (data && Array.isArray(data.extensions) && data.extensions.length) {
      runtimePolicy = {
        extensions: data.extensions.map((e) => e.replace(/^\\./, '').toLowerCase()),
        max_file_bytes: data.max_file_bytes || MAX_UPLOAD_BYTES,
      }
    }
  } catch {
    // 拉取失败 → 保持静态兜底（前端预检只是提示层，真正的强制点在后端）
    runtimePolicy = null
  }
}

/** 当前生效的扩展名白名单（运行时优先）。 */
export function effectiveAllowedExtensions(): readonly string[] {
  return runtimePolicy ? runtimePolicy.extensions : ALLOWED_UPLOAD_EXTENSIONS
}

/** 当前生效的单文件大小上限（运行时优先）。 */
export function effectiveMaxUploadBytes(): number {
  return runtimePolicy ? runtimePolicy.max_file_bytes : MAX_UPLOAD_BYTES
}`,
], 'upload-policy.ts：运行时拉取'), [
  `export function checkUploadFile(file: { name: string; size: number }): string | null {
  if (file.size > MAX_UPLOAD_BYTES) {
    return \`文件超过大小上限（\${formatBytes(MAX_UPLOAD_BYTES)}），请压缩后再上传\`
  }
  const ext = extensionOf(file.name)
  if (!ext) return \`文件缺少扩展名，无法判定类型：\${file.name}\`
  if (DENIED_UPLOAD_EXTENSIONS.includes(ext)) {
    return \`禁止上传可执行文件类型（.\${ext}）\`
  }
  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
    return \`不支持的文件类型（.\${ext}），仅支持图片 / 文档 / 文本 / 代码文件\`
  }
  return null
}`,
  `export function checkUploadFile(file: { name: string; size: number }): string | null {
  const maxBytes = effectiveMaxUploadBytes()
  if (file.size > maxBytes) {
    return \`文件超过大小上限（\${formatBytes(maxBytes)}），请压缩后再上传\`
  }
  const ext = extensionOf(file.name)
  if (!ext) return \`文件缺少扩展名，无法判定类型：\${file.name}\`
  // 禁止清单**永远生效**（可执行文件任何情况下都拒）
  if (DENIED_UPLOAD_EXTENSIONS.includes(ext)) {
    return \`禁止上传可执行文件类型（.\${ext}）\`
  }
  // 白名单以**后端为准**（P4-04）
  if (!effectiveAllowedExtensions().includes(ext)) {
    return \`不支持的文件类型（.\${ext}），仅支持图片 / 文档 / 文本 / 代码文件\`
  }
  return null
}`,
], 'upload-policy.ts：checkUploadFile 用运行时白名单'),
])

// ============================================================ P4-13 挂载 WorkspacePicker
patch('views/WorkspaceView.vue', [[
  `          :workspace="workspaceName"
          :permissive="permissive"
          :level="permissions.effectiveLevel"
          @workspace="workspaceName = ''"`,
  `          :workspace="workspaceName"
          :permissive="permissive"
          :level="permissions.effectiveLevel"
          @workspace="workspacePickerVisible = true"`,
], 'WorkspaceView：工作空间按钮打开选择器'), [
  `const workspaceName = ref('')`,
  `const workspaceName = ref('')
// P4-13：工作空间选择器此前是**孤儿组件**（全仓无引用）→ 按钮点了没反应
const workspacePickerVisible = ref(false)

/** P4-13：选中工作空间 → 写当前空间名并绑定到当前任务 */
async function onPickWorkspace(id: string): Promise<void> {
  workspacePickerVisible.value = false
  try {
    const data = await workspacesList()
    const hit = data.items.find((w) => w.id === id)
    workspaceName.value = hit?.name || id
  } catch {
    workspaceName.value = id
  }
  const sessionId = ws.currentTaskId
  if (sessionId) ws.assignSpace(sessionId, id)
}`,
], 'WorkspaceView：选择器回调'), [
  `import ContextBar from '@/components/composer/ContextBar.vue'`,
  `import ContextBar from '@/components/composer/ContextBar.vue'
import WorkspacePicker from '@/components/composer/WorkspacePicker.vue'`,
], 'WorkspaceView：引入 WorkspacePicker'),
])
