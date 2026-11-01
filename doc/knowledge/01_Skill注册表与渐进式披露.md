# Skill 注册表与渐进式披露

> **依据代码**：`apps/server/src/domain/skill/manager.ts`、`apps/server/src/http/routes/skills.ts`、`skills/`（2026-11-01 复核重写）
> **原理主题**：Agent Skill 的**渐进式披露（Progressive Disclosure）**与
> 「文件系统为真、DB 为状态」的注册表模型。

---

## 一、什么是 Skill

一个 Skill = 一个目录，内含 `SKILL.md`（YAML frontmatter：name + description；
正文为 Markdown 指令）+ 任意附属资源（脚本、模板、参考文档）。
它教 Agent「做某类事的流程」，等价于一份**可被模型按需读取的岗位手册**。

本项目内置 6 个（`skills/`）：`data-analysis`（pandas 数据分析）、
`frontend-design`（前端界面生成）、`marketing-materials`（营销素材批量生成）、
`pdf`（PDF 处理）、`ralph-loop`（AI 循环脚本生成）、`skill-creator`（创建/优化 Skill）。

## 二、原理：渐进式披露

上下文窗口是稀缺资源。若把 6 份手册全文塞进 system prompt，每次调用都浪费
几千 token，还会稀释模型注意力。渐进式披露把信息分三层，**按需展开**：

| 层 | 内容 | 本项目实现 |
|---|---|---|
| L1 目录 | name + 一句话 description | `listSkills()`（`manager.ts:129`）；注入 system prompt 的只有这一层 |
| L2 摘要 | + 资源文件清单 | `listSummaries()`（`manager.ts:146`），管理界面用 |
| L3 全文 | SKILL.md 正文 + 资源内容 | `getSkill(name)`（`manager.ts:171`）；模型用 `read_file` 工具自取 |

关键设计：**模型自己决定何时展开**。system prompt 只写
`## 可用 Skill\n- name: description`（`buildSystemPrompt()`，`manager.ts:409`），
模型判断任务匹配某个 Skill 后，用 `read_file` 读 `SKILL.md` 全文——
「读指令」这个动作本身走统一的文件工具与只读可信根（`../analysis/14` §3），
不需要为 Skill 发明第二套机制。

### 与 Anthropic Agent Skills 规范的对照

同：目录 + SKILL.md + frontmatter（name/description）+ 附属资源 + 渐进披露。
异：本项目把「启用/禁用」状态放进 SQLite（`skills` 表），支持运行时切换与
管理 API；Anthropic 规范只定义文件格式。

## 三、原理：双源注册表（文件为真、DB 为状态）

- **内容以文件系统为唯一真相源**——Skill 是用户可编辑、可 git 管理、可 zip
  分享的文件；
- **状态在 DB**：`enabled` / `stale` / `updated_at`（`skills` 表）；
- **启动时单向同步** `syncToDb()`（`manager.ts:338`）：磁盘 → DB（upsert 元信息），
  磁盘消失 → 标 `stale=1`（**不删行**——保留用户曾经的禁用决策与审计轨迹）；
- **同名覆盖**：自定义目录（`userData/skills_custom/`）优先于内置目录——
  用户无需改安装包就能覆盖内置行为；
- **内置只读**：内置 Skill 不可删、不可改正文（`manager.ts:263/283`），
  保护随包分发的内容不被误改。

## 四、匹配与选择

`matchSkills(query, top_k=3)`（`manager.ts:194`）：整串命中 +2 分、逐 token +1 分，
降序取 top-k。这是**关键词启发式**而非语义检索——Skill 数量小（个位数到几十），
关键词足够；数量再大时应换 embedding 检索。

运行时选择路径（`../analysis/03` §一）：`skills` 参数显式指定，或 `team_id`
经团队解析（二选一，互斥 422）；chat 模式未显式选择则不注入。

## 五、导入导出与路径安全

- 导出：目录文件清单（逐文件文本）；
- 导入（`routes/skills.ts:118`）：base64 zip → AdmZip 解包 →
  **逐 entry 拦截** `..` 与绝对路径 → 写自定义目录 → `syncToDb()`；
- 资源读取：`isInside()` 前缀校验（`manager.ts:71`），防 `../../etc/passwd`；
- 资源路由支持多段路径（`/skills/{name}/files/*`）。

## 六、业界对照

| 系统 | 披露方式 | 注册表 |
|---|---|---|
| Anthropic Agent Skills | 三级（name → description → 正文/资源） | 文件系统 |
| Claude Code plugins | manifest + 目录 | 市场 + 本地 |
| 本项目 | 三级（同 Anthropic） | 文件系统（内容）+ SQLite（状态） |

## 参考

- `../analysis/00` §7 R-10（Anthropic Agent Skills 规范）
- `../analysis/02` §一（Skill 链事实描述）
