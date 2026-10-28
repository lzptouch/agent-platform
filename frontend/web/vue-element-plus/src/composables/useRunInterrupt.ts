/**
 * 运行中干预（S4）：停止（真中止）与追加指令（工具边界注入）。
 *
 * 语义要点（诚实优先）：
 * - 停止以**后端状态**为准：先 `runCancel`，前端 abort 只作连接层清理；
 * - 追加指令在**下一个工具边界**生效；若当前正在执行命令，则命令结束后才生效——
 *   UI 必须如实说明，不得显示"已生效"。
 */
import { ref } from 'vue'
import { runCancel, runSteer } from '@/api/desktop'

export const STEER_PENDING_NOTE = '将在下一个工具边界生效；若命令正在执行，则命令结束后生效'
export const CANCEL_PENDING_NOTE = '已请求停止（正在执行的命令结束后生效）'

export function useRunInterrupt() {
  /** 正在提交追加指令 */
  const steering = ref(false)
  /** 停止请求已发出 */
  const stopping = ref(false)

  async function stopRun(runId: string | null | undefined): Promise<boolean> {
    if (!runId) return false
    stopping.value = true
    try {
      await runCancel(runId)
      return true
    } catch {
      // 后端可能已结束（幂等）
      return false
    } finally {
      stopping.value = false
    }
  }

  async function submitSteer(
    runId: string | null | undefined,
    text: string,
    mode: 'append' | 'replace_plan' = 'append',
  ): Promise<boolean> {
    const instruction = (text || '').trim()
    if (!runId || !instruction) return false
    steering.value = true
    try {
      await runSteer(runId, instruction, mode)
      return true
    } catch {
      return false
    } finally {
      steering.value = false
    }
  }

  return { steering, stopping, stopRun, submitSteer }
}
