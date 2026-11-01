import { describe, it, expect } from 'vitest'
import {
  ALLOWED_UPLOAD_EXTENSIONS,
  DENIED_UPLOAD_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  checkUploadFile,
  formatBytes,
} from './upload-policy'

describe('上传前预检（批次 01 / WP-2）', () => {
  it('普通文本文件放行', () => {
    expect(checkUploadFile({ name: 'readme.txt', size: 1024 })).toBeNull()
    expect(checkUploadFile({ name: 'main.py', size: 1024 })).toBeNull()
    expect(checkUploadFile({ name: 'shot.PNG', size: 1024 })).toBeNull()
  })

  it('可执行文件被拒', () => {
    const reason = checkUploadFile({ name: 'malware.exe', size: 10 })
    expect(reason).toBeTruthy()
    expect(reason).toContain('禁止上传可执行文件')
    for (const ext of DENIED_UPLOAD_EXTENSIONS) {
      expect(checkUploadFile({ name: `x.${ext}`, size: 10 })).toBeTruthy()
    }
  })

  it('白名单外的类型被拒', () => {
    expect(checkUploadFile({ name: 'archive.zip', size: 10 })).toContain('不支持的文件类型')
    expect(checkUploadFile({ name: 'noext', size: 10 })).toContain('缺少扩展名')
  })

  it('超过大小上限被拒', () => {
    const reason = checkUploadFile({ name: 'big.txt', size: MAX_UPLOAD_BYTES + 1 })
    expect(reason).toContain('大小上限')
    expect(checkUploadFile({ name: 'ok.txt', size: MAX_UPLOAD_BYTES })).toBeNull()
  })

  it('白名单与禁止清单不重叠', () => {
    for (const ext of DENIED_UPLOAD_EXTENSIONS) {
      expect(ALLOWED_UPLOAD_EXTENSIONS).not.toContain(ext)
    }
  })

  it('字节数格式化可读', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB')
  })
})
