"""F-ENG-04 · web 前端消费桌面后端事件（渲染进程侧终于有消费者）。"""
from pathlib import Path

ROOT = Path("/Users/lizhipeng/workspace/project/agent/frontend/web/vue-element-plus/src")


def patch(rel: str, pairs, label: str) -> None:
    path = ROOT / rel
    t = path.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in t:
            raise SystemExit(f"❌ {label}: 锚点未命中 {a[:70]!r}")
        t = t.replace(a, b, 1)
    path.write_text(t, encoding="utf-8")
    print(f"✅ {label}")


patch("views/WorkspaceView.vue", [
    # 1) 状态 + 订阅函数
    (
        """/** P4-14：订阅壳广播的后端状态（Web 形态无桥 → 不订阅）。 */
function subscribeBackendState(): void {""",
        """/** P4-ENG-04：桌面后端事件（`workspace_changed` / `permission_requested` 等）。 */
const backendEvents = ref<{ type: string; at: number }[]>([])

/** 最近一条事件的**可读**描述（用于顶栏提示）。 */
const backendEventHint = computed(() => {
  const top = backendEvents.value[0]
  if (!top) return ''
  switch (top.type) {
    case 'workspace_changed':
      return '工作空间已切换'
    case 'permission_requested':
      return '有一项操作等待审批'
    case 'permission_resolved':
      return '审批已完成'
    case 'scheduler_rescued':
      return '调度已恢复'
    default:
      return `后端事件：${top.type}`
  }
})

/**
 * F-ENG-04：订阅壳转发的后端事件。
 *
 * 此前 `onBackendEvent` **只有类型声明、没有消费者** → 事件到了渲染进程
 * 却无人处理（「桌面事件桥贯通」的验收不成立）。
 *
 * 同时把最近事件挂到 `window.__agentBackendEvents`（排障 + e2e 断言用）。
 */
function subscribeBackendEvents(): void {
  const bridge = window.agentDesktop
  if (!bridge?.onBackendEvent) return
  bridge.onBackendEvent((raw: unknown) => {
    const evt = (raw || {}) as { type?: string }
    const item = { type: evt.type || 'unknown', at: Date.now() }
    backendEvents.value = [item, ...backendEvents.value].slice(0, 50)
    const w = window as unknown as { __agentBackendEvents?: unknown[] }
    w.__agentBackendEvents = w.__agentBackendEvents || []
    w.__agentBackendEvents.push(item)
  })
}

/** P4-14：订阅壳广播的后端状态（Web 形态无桥 → 不订阅）。 */
function subscribeBackendState(): void {""",
    ),
    # 2) onMounted 里同时订阅事件
    (
        """  // P4-14：订阅后端状态广播（降级态）
  subscribeBackendState()""",
        """  // P4-14：订阅后端状态广播（降级态）
  subscribeBackendState()
  // F-ENG-04：订阅后端事件（渲染进程侧消费者）
  subscribeBackendEvents()""",
    ),
], "WorkspaceView.vue：事件消费者")

# 3) 模板：顶栏提示
p = ROOT / "views/WorkspaceView.vue"
t = p.read_text(encoding="utf-8")
if "backendEventHint" not in t.split("<template>")[1].split("</template>")[0]:
    anchor = """    <!-- P4-14：后端状态**降级态**提示（sidecar 崩溃 / 重启中） -->"""
    new = """    <!-- F-ENG-04：后端事件提示（工作空间切换 / 待审批等） -->
    <div v-if="backendEventHint" class="event-hint">
      <el-icon><InfoFilled /></el-icon><span>{{ backendEventHint }}</span>
    </div>

    <!-- P4-14：后端状态**降级态**提示（sidecar 崩溃 / 重启中） -->"""
    assert anchor in t
    t = t.replace(anchor, new, 1)
    # 样式
    if ".event-hint {" not in t:
        t = t.replace(".error-bar {", """.event-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--el-color-primary, #409eff);
  border-bottom: 1px solid var(--border-color, #e6e6e6);
}
.error-bar {""", 1)
    p.write_text(t, encoding="utf-8")
    print("✅ WorkspaceView.vue：事件提示已渲染")
