/**
 * 上传前预检（批次 01 / WP-2 · 1.2.4）。
 *
 * 与后端 `backend/app/core/uploads.py` 保持同一份白名单口径：
 * 图片 / 文档 / 文本 / 代码放行，可执行文件拒绝，单文件大小上限 50 MB。
 *
 * 前端先拦一道只是为了**给出可读提示**；真正的强制点在后端。
 */

/** 单文件大小上限（50 MB，与后端 `upload_max_file_bytes` 默认值一致） */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

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
  if (file.size > MAX_UPLOAD_BYTES) {
    return `文件超过大小上限（${formatBytes(MAX_UPLOAD_BYTES)}），请压缩后再上传`
  }
  const ext = extensionOf(file.name)
  if (!ext) return `文件缺少扩展名，无法判定类型：${file.name}`
  if (DENIED_UPLOAD_EXTENSIONS.includes(ext)) {
    return `禁止上传可执行文件类型（.${ext}）`
  }
  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
    return `不支持的文件类型（.${ext}），仅支持图片 / 文档 / 文本 / 代码文件`
  }
  return null
}
