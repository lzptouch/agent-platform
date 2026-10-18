# 设计 Token（Design Tokens）

> 以历史 `web/vue-vite-baseline/` 的 `style.css` 为基线对照（该实现已移除，见 §6），
> 当前实际取值以 `web/vue-element-plus/src/styles/tokens.css` 为准。

## 1. 颜色

### 主色（accent）

```css
--accent:       #4d6bfe;  /* 主操作 */
--accent-hover: #3b5bec;
--accent-light: #eef2ff;  /* 主色淡背景 */
```

### 链路语义色（与后端 `tool_source` 一致）

| tool_source | CSS 变量 | 颜色 | 用途 |
|---|---|---|---|
| `builtin` | `--accent` | `#4d6bfe` | 内置工具 |
| `mcp` | `--purple` | `#8b5cf6` | MCP Server 工具 |
| `rag` | `--green` | `#22a06b` | 本地文档 RAG |
| `web` | `--orange` | `#d97706` | Web Research |
| `plan` | `--teal` | `#0ea5b7` | 反思模式的 plan/reflection_plan 步骤卡（前端自造） |

> ⚠️ 没有"反思"独立色。`plan` 与 `reflection_plan` 共用 `--teal`。

### 状态色

```css
--red:   #e5484d;  /* 错误 */
--green: #22a06b;  /* 成功 */
--orange:#d97706;  /* 警告 */
```

### 中性色

```css
--bg:           #ffffff;
--bg-sidebar:   #f7f8fa;
--bg-hover:     #eceef1;
--bg-bubble-user:#e3efff;
--bg-code:      #f4f5f7;

--border:        #e5e7eb;
--border-strong: #d6d9de;

--text:        #1f2329;
--text-dim:    #8a919e;
--text-faint:  #b3b9c2;
```

### 暗色模式（Web/桌面必做，移动端跟随系统）

```css
@media (prefers-color-scheme: dark) {
  :root, html.dark {
    --bg:           #0f1115;
    --bg-sidebar:   #161922;
    --bg-hover:     #1f2330;
    --bg-bubble-user:#1e2a44;
    --bg-code:      #1a1d24;
    --border:       #2a2f3a;
    --border-strong:#3a4150;
    --text:         #e6e8eb;
    --text-dim:     #8a919e;
    --text-faint:   #5a6270;
  }
}
```

## 2. 圆角 / 阴影 / 间距

```css
--radius:    14px;
--radius-sm: 8px;
--radius-lg: 18px;

--shadow-sm: 0 1px 2px rgba(15,17,21,0.06);
--shadow-md: 0 6px 24px rgba(15,17,21,0.08);
```

间距网格 4/8 pt。

## 3. 字体

- 中文：`"PingFang SC", "Microsoft YaHei", system-ui, sans-serif`
- 等宽：`"JetBrains Mono", "Consolas", monospace`
- 基线：`font-size: 14px; line-height: 1.6`

## 4. Markdown 代码块

```css
.msg-body pre {
  background: #2b2f36;
  color: #e6e8eb;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
}
```

## 5. 图标与 Emoji

**不得用 emoji 当图标**。Web 用 Iconify 或各自 UI 库图标集。

## 6. 历史基线（`vue-vite-baseline`，已移除）实测值

> 记录来源：已删除的 `web/vue-vite-baseline/` 的 `style.css`（601 行）。
> 该实现已于 2026-10-19 随前端收敛一并移除，**仅作历史对照**；
> 当前默认前端 `web/vue-element-plus` 的实际 Token 见 `src/styles/tokens.css`。

- `--accent: #4d6bfe`
- 5 色映射：
  - `builtin` → `#4d6bfe`
  - `mcp` → `#8b5cf6`
  - `rag` → `#22a06b`
  - `web` → `#d97706`
  - `plan` → `#0ea5b7`
- `--radius: 14px`
- `--bg: #ffffff` / `--bg-sidebar: #f7f8fa`
- 无任何暗色主题（无 `prefers-color-scheme` / `.dark`）—— 当前实现已通过 CSS 变量 + `prefers-color-scheme` 补齐