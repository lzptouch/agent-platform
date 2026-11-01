import { describe, expect, it, vi } from 'vitest'

import { CANCEL_PENDING_NOTE, STEER_PENDING_NOTE, useRunInterrupt } from '../../../../apps/ui/src/composables/useRunInterrupt'

const runCancel = vi.fn(async () => ({ ok: true, status: 'interrupted' }))
const runSteer = vi.fn(async () => ({ ok: true, status: 'queued' }))

vi.mock('@/api/desktop', () => ({
  runCancel: (...a: unknown[]) => runCancel(...(a as [])),
  runSteer: (...a: unknown[]) => runSteer(...(a as [])),
}))

describe('useRunInterrupt（S4 运行中干预）', () => {
  it('停止调用 runCancel（以后端状态为准）', async () => {
    const { stopRun } = useRunInterrupt()
    const ok = await stopRun('run-1')
    expect(ok).toBe(true)
    expect(runCancel).toHaveBeenCalledWith('run-1')
  })

  it('无 runId 时不发请求', async () => {
    const { stopRun } = useRunInterrupt()
    expect(await stopRun(null)).toBe(false)
    expect(runCancel).not.toHaveBeenCalled()
  })

  it('追加指令提交成功并带 mode', async () => {
    const { submitSteer } = useRunInterrupt()
    const ok = await submitSteer('run-1', '改用表格输出', 'replace_plan')
    expect(ok).toBe(true)
    expect(runSteer).toHaveBeenCalledWith('run-1', '改用表格输出', 'replace_plan')
  })

  it('空指令不提交', async () => {
    const { submitSteer } = useRunInterrupt()
    expect(await submitSteer('run-1', '   ')).toBe(false)
  })

  it('提示文案诚实：命令执行中不显示"已生效"', () => {
    expect(STEER_PENDING_NOTE).toContain('命令结束后生效')
    expect(STEER_PENDING_NOTE).not.toContain('已生效')
    expect(CANCEL_PENDING_NOTE).toContain('结束后生效')
  })

  it('后端失败时不抛异常', async () => {
    runCancel.mockRejectedValueOnce(new Error('boom'))
    const { stopRun } = useRunInterrupt()
    expect(await stopRun('run-x')).toBe(false)
  })
})
