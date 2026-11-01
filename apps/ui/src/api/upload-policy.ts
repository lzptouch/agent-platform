/**
 * 上传前预检（批次 01 / WP-2 · 1.2.4）。
 *
 * 与后端 `apps/server/src/shared/config.ts` 保持同一份白名单口径：
 * 图片 / 文档 / 文本 / 代码放行，可执行文件拒绝，单文件大小上限 50 MB。
 *
 * 前端先拦一道只是为了**给出可读提示**；真正的强制点在后端。
 */

/** 单文件大小上限（50 MB，与后端 `upload_max_file_bytes` 默认值一致） */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/**
 * **P4-04**：上传白名单此前有**三份**（本文件、后端内置清单、环境变量覆盖）→
 * 前端拦下的扩展名后端可能放行（或反之）。
 *
 * 现在白名单以**后端为准**：拉取 `GET /api/v1/files/policy`，
 * 拉取失败则回退到本文件的静态兜底值。
 */

/** 后端当前生效的上传策略（未拉取时为 null → 用静态兜底） */
let runtimePolicy: { extensions: string[]; max_file_bytes: number } | null = null

/** 拉取后端当前生效的上传策略（带本地兜底，失败不抛错）。 */
export async function loadUploadPolicy(): Promise<void> {
  try {
    const { get } = await import('@/api/client')
    const data = await get<{ extensions: string[]; max_file_bytes: number }>(
      '/api/v1/files/policy',
    )
    if (data && Array.isArray(data.extensions) && data.extensions.length) {
      runtimePolicy = {
        extensions: data.extensions.map((e) => e.replace(/^\./, '').toLowerCase()),
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
}

const IMAGE = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg', 'ico', 'tif', 'tiff']
const DOC = [
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
  'rtf', 'epub',
]
const TEXT = [
  'txt', 'md', 'markdown', 'csv', 'tsv', 'json', 'jsonl', 'yaml', 'yml',
  'toml', 'ini', 'cfg', 'conf', 'xml', 'html', 'htm', 'log',
]
const CODE = [
  'py', 'pyi', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'java', 'kt',
  'c', 'h', 'cpp', 'hpp', 'cc', 'cs', 'go', 'rs', 'rb', 'php', 'swift',
  'scala', 'sh', 'bash', 'zsh', 'sql', 'r', 'm', 'lua',
  'vue', 'svelte', 'ipynb',
]

/** 允许的扩展名（无点，小写） */
export const ALLOWED_UPLOAD_EXTENSIONS: readonly string[] = [
  ...IMAGE,
  ...DOC,
  ...TEXT,
  ...CODE,
]

/** 明确禁止的可执行 / 二进制类型（无点，小写） */
export const DENIED_UPLOAD_EXTENSIONS: readonly string[] = [
  'exe', 'dll', 'com', 'bat', 'cmd', 'scr', 'msi', 'msp', 'sys', 'cpl',
  'ps1', 'vbs', 'wsf', 'hta', 'jar', 'apk', 'so', 'dylib', 'deb', 'rpm',
  'app', 'pkg', 'whl', 'pyd', 'pyc', 'pyo', 'bin', 'elf', 'o', 'a',
  'node', 'lnk', 'url', 'reg',
]

function extensionOf(name: string): string {
  const idx = name.lastIndexOf('.')
  if (idx < 0 || idx === name.length - 1) return ''
  return name.slice(idx + 1).toLowerCase()
}

/** 人类可读的字节数 */
export function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(0)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${size} B`
}

/**
 * 预检上传文件。
 *
 * @returns 拒绝原因（可读中文提示）；`null` 表示放行。
 */
export function checkUploadFile(file: { name: string; size: number }): string | null {
  const maxBytes = effectiveMaxUploadBytes()
  if (file.size > maxBytes) {
    return `文件超过大小上限（${formatBytes(maxBytes)}），请压缩后再上传`
  }
  const ext = extensionOf(file.name)
  if (!ext) return `文件缺少扩展名，无法判定类型：${file.name}`
  // 禁止清单**永远生效**（可执行文件任何情况下都拒）
  if (DENIED_UPLOAD_EXTENSIONS.includes(ext)) {
    return `禁止上传可执行文件类型（.${ext}）`
  }
  // 白名单以**后端为准**（P4-04）
  if (!effectiveAllowedExtensions().includes(ext)) {
    return `不支持的文件类型（.${ext}），仅支持图片 / 文档 / 文本 / 代码文件`
  }
  return null
}
