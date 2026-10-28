import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import router from './index'

const SIDE_NAV = path.resolve(__dirname, '..', 'components', 'layout', 'SideNav.vue')

/**
 * 从侧栏源码里抽出所有跳转目标。
 *
 * 两种写法都要覆盖：
 * - `go('/xxx')` 字面量；
 * - 统一导航数组里的 `{ path: '/xxx', ... }`。
 */
function navTargets(): string[] {
  const src = fs.readFileSync(SIDE_NAV, 'utf-8')
  const out: string[] = []
  const push = (p: string) => {
    if (p.startsWith('/') && !out.includes(p)) out.push(p)
  }
  for (const re of [/go\(\s*['"]([^'"]+)['"]\s*\)/g, /path:\s*['"]([^'"]+)['"]/g]) {
    let m: RegExpExecArray | null
    while ((m = re.exec(src)) !== null) push(m[1])
  }
  return out
}

describe('路由护栏（S8 修复白屏）', () => {
  it('侧栏的每个跳转目标都存在（非兜底路由）', () => {
    const targets = navTargets()
    expect(targets.length).toBeGreaterThan(0)
    const missing: string[] = []
    for (const t of targets) {
      const resolved = router.resolve(t)
      // 命中兜底 404 说明这条路径没有真实路由
      const isNotFound = resolved.matched.some(
        (r) => r.path.includes('pathMatch') || String(r.redirect).includes('pathMatch'),
      )
      if (!resolved.matched.length || isNotFound) missing.push(t)
    }
    expect(missing, `侧栏指向了不存在的路由：${missing.join(', ')}`).toEqual([])
  })

  it('侧栏的目标包含助理与项目入口', () => {
    const targets = navTargets()
    expect(targets).toContain('/assistant')
    expect(targets).toContain('/spaces')
  })

  it('未知路径命中 404 兜底而不是空白', () => {
    const resolved = router.resolve('/definitely-not-a-real-route')
    expect(resolved.matched.length).toBeGreaterThan(0)
    const isNotFound = resolved.matched.some((r) => r.path.includes('pathMatch'))
    expect(isNotFound).toBe(true)
  })

  it('助理与项目路由可解析到真实组件', () => {
    for (const path of ['/assistant', '/spaces']) {
      const resolved = router.resolve(path)
      const isNotFound = resolved.matched.some((r) => r.path.includes('pathMatch'))
      expect(isNotFound, `${path} 不应命中兜底`).toBe(false)
      expect(resolved.matched.length).toBeGreaterThan(0)
    }
  })
})
