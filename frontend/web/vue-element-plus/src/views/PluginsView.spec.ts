import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import PluginsView from './PluginsView.vue'

const pluginsList = vi.fn(async () => ({ items: [] }))
const pluginScan = vi.fn(async (_p?: string) => ({
  level: 'high',
  findings: [{ rule: 'network_call', level: 'medium', reason: '命中网络调用', path: 'x.py' }],
  scanned_files: 3, total_bytes: 100,
  requires_confirmation: true, rejected_by_default: true,
}))
const pluginInstall = vi.fn(async (_p?: Record<string, unknown>) => ({
  ok: false, name: 'x', version: '1.0.0', message: '扫描等级 high，默认拒绝安装（需显式确认）',
  scan: { level: 'high', rejected_by_default: true },
}))
const pluginRollback = vi.fn(async (_n?: string, _v?: string) => ({ ok: true, message: '已回滚到上一版本' }))

vi.mock('@/api', () => ({
  pluginsList: () => pluginsList(),
  pluginScan: (p: string) => pluginScan(p),
  pluginInstall: (p: Record<string, unknown>) => pluginInstall(p),
  pluginRollback: (n: string, v: string) => pluginRollback(n, v),
}))

const globalPlugins = { global: { plugins: [ElementPlus] } }

describe('PluginsView', () => {
  it('安装前可扫描并显示等级', async () => {
    const w = mount(PluginsView, globalPlugins)
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    ;(w.vm as unknown as { installPath: string }).installPath = '/tmp/pkg'
    await (w.vm as unknown as { previewScan: () => Promise<void> }).previewScan()
    await w.vm.$nextTick()
    expect(w.text()).toContain('扫描等级')
    expect(w.text()).toContain('high')
    expect(pluginScan).toHaveBeenCalledWith('/tmp/pkg')
  })

  it('high 默认拒绝需显式确认', async () => {
    const w = mount(PluginsView, globalPlugins)
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    ;(w.vm as unknown as { installPath: string }).installPath = '/tmp/pkg'
    await (w.vm as unknown as { install: () => Promise<void> }).install()
    expect(pluginInstall).toHaveBeenCalled()
    const payload = pluginInstall.mock.calls[0][0] as Record<string, unknown>
    expect(payload.confirm).toBe(false)
  })

  it('扫描到 high 后安装需显式确认（confirm=true）', async () => {
    const w = mount(PluginsView, globalPlugins)
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    ;(w.vm as unknown as { installPath: string }).installPath = '/tmp/pkg'
    await (w.vm as unknown as { previewScan: () => Promise<void> }).previewScan()
    await (w.vm as unknown as { install: () => Promise<void> }).install()
    const payload = pluginInstall.mock.calls[pluginInstall.mock.calls.length - 1][0] as Record<string, unknown>
    expect(payload.confirm).toBe(true)
  })

  it('回滚可用', async () => {
    pluginsList.mockResolvedValueOnce({
      items: [{ id: 1, name: 'p', version: '2.0.0', status: 'installed', scan: { level: 'low' }, manifest: {}, installed_at: null }] as never,
    })
    const w = mount(PluginsView, globalPlugins)
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    await (w.vm as unknown as { rollback: (r: { name: string; version: string }) => Promise<void> })
      .rollback({ name: 'p', version: '2.0.0' })
    expect(pluginRollback).toHaveBeenCalledWith('p', '2.0.0')
  })
})
