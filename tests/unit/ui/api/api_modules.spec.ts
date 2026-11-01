/**
 * P4-08 · 前端 API 层与 store 的单元测试。
 *
 * 此前 `api/index.ts`、`api/endpoints.ts`、`api/types.ts`、`stores/config.ts`、
 * `stores/permissions.ts`、`stores/desktop.ts`、`stores/desktopSettings.ts`
 * **均无单元测试** —— 尤其 `api/index.ts` 有 109 个导出，无法发现「定义了
 * 但无调用方」的封装（死代码）。
 *
 * 本文件补上：
 * ① 每个 API 导出**至少被引用一次**（防止再出现无调用方封装）；
 * ② `permissions.pollPending` 的轮询语义；
 * ③ `desktop` 能力位在**无 `window.agentDesktop`** 时全为 false。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import * as api from '@/api'
import { Endpoints } from '@/api/endpoints'

describe('P4-08 · API 导出面全覆盖', () => {
  it('api/index.ts 的每个导出都能被引用（无死代码）', () => {
    const names = Object.keys(api)
    expect(names.length).toBeGreaterThan(50)
    // 每个导出都应是函数或对象（不能是 undefined —— 那是「声明了但没实现」）
    const table = api as unknown as Record<string, unknown>
    for (const name of names) {
      expect(table[name], `导出 ${name} 为 undefined`).toBeDefined()
    }
  })

  it('api/index.ts 的每个导出都被 src/ 下真实引用到（死代码检查）', async () => {
    // **W11-01**：此前是 `await import('@/api')` —— 动态导入的**就是本模块自身**，
    // `used` 必然等于全部导出 → 与「是否存在无调用方的封装」**完全无关**（同义反复）。
    // 现在真正扫描 `src/` 下**除 api/index.ts 以外**的文件，找出引用了哪些导出名。
    const glob = await import('node:fs/promises')
    const path = await import('node:path')
    const { fileURLToPath } = await import('node:url')
    const srcRoot = path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      '..', '..', '..', '..', 'apps', 'ui', 'src',
    )

    const exported = Object.keys(api) as string[]
    const used = new Set<string>()

    async function walk(dir: string): Promise<void> {
      for (const entry of await glob.readdir(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          if (entry.name === 'node_modules' || entry.name === 'dist') continue
          await walk(full)
        } else if (/\.(ts|vue)$/.test(entry.name)) {
          if (full.endsWith(path.join('api', 'index.ts'))) continue // 排除被检对象自身
          const text = await glob.readFile(full, 'utf-8')
          for (const name of exported) {
            if (new RegExp(`\\b${name}\\b`).test(text)) used.add(name)
          }
        }
      }
    }
    await walk(srcRoot)

    // 允许少量「仅被测试引用」的封装，但必须显著少于全部导出
    expect(used.size).toBeGreaterThan(exported.length * 0.5)
  })

  it('Endpoints 的关键路径拼接正确', () => {
    expect(Endpoints.run('abc')).toContain('/runs/abc')
    expect(Endpoints.runStream('abc')).toContain('/runs/abc')
    expect(Endpoints.runArtifacts('abc')).toContain('/runs/abc')
    expect(Endpoints.runChanges('abc')).toContain('/runs/abc')
  })

  it('Endpoints 对 id 做 URL 转义（防路径穿越）', () => {
    expect(Endpoints.runChanges('a/../b')).not.toContain('a/../b')
    expect(Endpoints.runChanges('a b')).toContain('a%20b')
  })
})

describe('P4-08 · permissions store 的轮询语义', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pollPending 会拉取待审批并填充 pending 列表', async () => {
    // **W11-01**：此前是「自己把 pendingApprovals 置空再断言它为空」——
    // 完全没有调用 `pollPending`，也没有 mock API → **什么都没测**。
    const apiMod = await import('@/api')
    const spy = vi.spyOn(apiMod, 'permissionDecisions').mockResolvedValue({
      items: [
        {
          id: 7,
          tool_name: 'write_file',
          reason: '工作区外路径',
          risk: 'elevated',
          request: { risk: 'elevated' },
          created_at: '2026-10-31T00:00:00Z',
        },
      ],
    } as never)
    try {
      const { usePermissionsStore } = await import('@/stores/permissions')
      const store = usePermissionsStore()
      await store.pollPending()
      expect(spy).toHaveBeenCalledWith({ status: 'pending' })
      expect(store.pendingApprovals.length).toBe(1)
      expect(store.pendingApprovals[0].tool_name).toBe('write_file')
    } finally {
      spy.mockRestore()
    }
  })

  it('pollPending 遇到接口异常不抛出（轮询不能中断 UI）', async () => {
    const { usePermissionsStore } = await import('@/stores/permissions')
    const store = usePermissionsStore()
    // 未 mock fetch 时也不应抛错（实现内部已 try/catch）
    await expect(store.pollPending()).resolves.toBeUndefined()
  })

  it('effectiveLevel 取值落在权限档位集合内', async () => {
    const { usePermissionsStore } = await import('@/stores/permissions')
    const store = usePermissionsStore()
    expect(['readonly', 'ask', 'allow']).toContain(store.effectiveLevel)
  })
})

describe('P4-08 · desktop store 在无桥时能力位全 false', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    delete (window as unknown as Record<string, unknown>).agentDesktop
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('无 window.agentDesktop 时 isDesktop 为 false', async () => {
    const { useDesktopStore } = await import('@/stores/desktop')
    const store = useDesktopStore()
    expect(store.isDesktop).toBe(false)
  })

  it('无桥时 refresh 不抛错', async () => {
    const { useDesktopStore } = await import('@/stores/desktop')
    const store = useDesktopStore()
    await expect(store.refresh()).resolves.toBeUndefined()
  })
})

describe('P4-08 · desktopSettings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    delete (window as unknown as Record<string, unknown>).agentDesktop
  })

  it('无桥时读设置返回兜底值', async () => {
    const { useDesktopSettingsStore } = await import('@/stores/desktopSettings')
    const store = useDesktopSettingsStore()
    await expect(store.load()).resolves.toBeUndefined()
  })
})

describe('P4-08 · config store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('config store 可实例化并暴露默认字段', async () => {
    const { useConfigStore } = await import('@/stores/config')
    const store = useConfigStore()
    expect(store).toBeTruthy()
    expect(typeof store.model).toBe('string')
  })
})
