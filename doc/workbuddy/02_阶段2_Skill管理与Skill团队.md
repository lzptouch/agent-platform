# 阶段 2：Skill 管理闭环 + Skill 团队 —— 代码修改计划与测试计划

> 前置：阶段 1（DB、run 账本、会话）
> 交付：可管理的 Skill（文件系统为内容真相 + DB 索引）、Team CRUD、三种编排策略、team 与 skills 互斥
> 影响文件：新增 6 个，修改 6 个

---

## 1. 目标

1. Skill 从"只读扫描"升级为可管理：创建 / 编辑 / 启停用 / 导入导出 / 删除。
2. 支持**内置（只读）+ 自定义（可写）**双目录，同名时自定义覆盖内置。
3. Skill 团队：`teams` + `team_skills` 两张表，绑定到会话或单次运行。
4. `strategy`：`none / sequential / router`，router 失败可降级。
5. 团队与 `skills[]` 互斥，避免语义冲突。

---

## 2. 设计决策（与 v1 的差异）

| 议题 | v1 | v2 决策与理由 |
| --- | --- | --- |
| Skill 存储 | 只读扫描 `skills/` | **内容仍在文件系统**（Agent 需 `read_file` 读 SKILL.md，且社区生态以目录+md 分发），**元数据/启停用状态入 DB**，启动时增量同步 |
| 用户自定义 Skill 位置 | 未定义 | `data/skills_custom/`（随数据卷持久化，升级不丢） |
| 团队技能关联 | JSON 数组 | `team_skills(team_id, skill_name, position)`，可反查引用、可排序 |
| router 策略 | 每次调用 LLM | 结果按 `(team_id, query_hash)` 缓存 5 分钟，避免多轮对话重复路由 |
| 团队与品牌 | 无 | 团队名唯一（`UNIQUE`），删除时会话 `team_id` 置 NULL |
| 内置 Skill 删除 | 403 | 保留；但允许**禁用**（不影响升级） |

---

## 3. 后端代码修改计划

### 3.1 数据库迁移 `0002_skills_teams.py`

```text
-- teams 表骨架已在 0001 建好（为 sessions.team_id 提供外键目标），本迁移只补充业务表
skills(name PK, description, source, path, frontmatter_json, enabled, updated_at)
team_skills(team_id FK CASCADE, skill_name, position, PK(team_id, skill_name))
CREATE INDEX idx_team_skills_skill ON team_skills(skill_name);
```

`skills.enabled` 默认 1；`source` ∈ `{builtin, custom}`。不给 `skill_name` 加外键到 `skills`，因为自定义 Skill 可能被目录删除而未同步——由服务层做一致性校验（避免迁移期间约束冲突）。

### 3.2 修改 `backend/app/core/config.py`

```python
skills_dir: Path = PROJECT_ROOT / "skills"          # 内置，只读
custom_skills_dir: Path = data_dir / "skills_custom"  # 用户，可写（随数据卷持久化）
skill_import_max_bytes: int = 20 * 1024 * 1024
skill_import_max_files: int = 500
```

`ensure_dirs()` 创建 `custom_skills_dir`。

### 3.3 修改 `backend/app/services/skill_manager.py`

**扫描**

- `reload()` 依次扫描 `custom_skills_dir`、`skills_dir`；同 `name` 时 custom 覆盖 builtin，并记录 `source`。
- 每个 Skill 增加字段：`source`、`enabled`（来自 DB，缺省 true）、`mtime`。
- 目录内 `SKILL.md` 解析失败 → 跳过并 `logger.warning`，不阻塞启动。
- 路径安全：所有返回给前端的 `path` 仍为相对路径；`get_resource_path()` 保留现有 `startswith(base)` 校验，并额外拒绝符号链接逃逸（`Path.resolve()` 后比较）。

**同步到 DB**

```python
def sync_to_db(self, db) -> dict:   # 启动时调用
    # upsert 每条 skill 的 name/description/source/path/frontmatter/mtime
    # DB 中不存在但磁盘已删除的记录：source=custom → 标记 stale 并禁用；
    # builtin 记录删除；最后清理 team_skills 中的孤儿引用并返回告警列表
```

**CRUD（写入文件 + 同步 DB，同一事务边界之外）**

- `create(name, description, content, db)`：校验 kebab-case、长度 ≤64、description ≤1024；目录不存在；写 `data/skills_custom/<name>/SKILL.md`（`---` frontmatter + 正文）；失败回滚删除目录；成功后 upsert DB。
- `update(name, description=None, content=None, db)`：仅允许 `source=custom`；内置返回 403；写前先 `validate_skill`。
- `set_enabled(name, enabled, db)`：仅改 DB；`list_skills()` 返回带 `enabled`。
- `delete(name, db)`：仅 `source=custom`；移动目录到 `data/skills_custom/.trash/<name>-<ts>`（软删除，可恢复），DB 标记 deleted；**不物理删除**用户内容。
- `export_zip(name)`：内存 zip（`ZIP_DEFLATED`），排除 `__pycache__/.DS_Store/*.pyc`；返回 `(bytes, filename)`，避免写临时文件。
- `import_zip(file_bytes, db)`：
  - 字节数 ≤ `skill_import_max_bytes`；文件数 ≤ 500；
  - 拒绝绝对路径、`..`、符号链接、`SKILL.md` 不在根或唯一一级目录内（允许 `zip` 打包时带一层顶层目录）；
  - 解压到 `data/skills_custom/.staging/<uuid>` → 校验 → 原子 `os.replace` 到目标目录；
  - 同名且 `source=builtin` → 409；同名 custom → 需 `overwrite=true`；
  - 完成后 `reload()` + `sync_to_db()`。

**Prompt 构建**

```python
def build_system_prompt(self, skill_names=None, *, mode="work", team=None, tools=None) -> str
```

- 工具清单按 `tools` 渲染（依赖阶段 1 的 `ToolProfile`）；
- `team` 注入顺序：
  1. `## 团队：{name}` + `prompt_prefix`
  2. `## 可用 Agent Skills`，`sequential` 时每条前缀 `[步骤 {i}/{n}]`，并附"按顺序执行，前一步产出作为后一步输入"；
  3. `router` 只注入被选中的子集（resolve 后传入）。
- `mode=chat` 且 `team` 存在时，注入团队提示但工具仍为只读档案（团队不能提权）。

### 3.4 新增 `backend/app/services/team_service.py`

```python
class TeamService:
    create(name, skill_names, description="", prompt_prefix="", strategy="none")
    list(include_disabled=True) -> list[TeamOut]      # 附带引用计数
    get(team_id) -> TeamDetail                        # 含 members(position 排序)
    update(team_id, **fields)
    delete(team_id)                                   # team_skills 级联；sessions.team_id SET NULL
    set_enabled(team_id, enabled)
    resolve(team_id, query=None, mode="work") -> ResolveResult
    validate_members(skill_names) -> (ok, missing)
```

**resolve 语义**

| strategy | 行为 |
| --- | --- |
| `none` | 返回全部成员（剔除 `enabled=false` 与磁盘已删除项），并附 `warnings[]` |
| `sequential` | 同上，按 `position` 排序，返回带 `step_index` 的成员 |
| `router` | 取候选 `name+description`，调 `core/llm.py` 的 LLM（`plan_model`，JSON mode）选 1~2 个；解析失败/超时 3s → 降级 `none` 并 `degraded=true` |

- 路由输入加约束："只输出 JSON 数组，元素必须是候选 name"；返回后与服务端候选集求交，防止幻觉名称。
- 缓存：进程内 LRU（`functools.lru_cache` 不适用带 query，需手工 dict + TTL 300s + 最大 256 条）。
- 团队成员为空 → resolve 直接返回空 + `warnings=["团队未配置可用 Skill"]`，不报错（保证可运行）。

### 3.5 新增 `backend/app/schemas/team.py`

```text
TeamCreate { name: 1..64, skill_names: list[str] min 1, description="",
             prompt_prefix="", strategy: Literal["none","sequential","router"]="none" }
TeamUpdate { 全可选, skill_names 若提供则整体替换 }
TeamOut    { id,name,description,skill_names,prompt_prefix,strategy,enabled,
             reference_count,created_at,updated_at }
ResolveOut { team_id, skills:[{name,enabled,step_index,description}],
             prompt_preview: str, strategy, degraded: bool, warnings: list[str] }
```

校验：`name` strip 后非空、唯一冲突 409；`skill_names` 去重且保持顺序；未知 Skill 名在**创建时**返回 422（严格要求），而非静默忽略；已禁用 Skill 允许加入但 resolve 时剔除并 warning。

### 3.6 新增 `backend/app/api/v1/teams.py` + 注册

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/teams?include_disabled=` | 列表（含成员与引用数） |
| POST | `/api/v1/teams` | 创建；重名 409 |
| GET/PUT/DELETE | `/api/v1/teams/{id}` | 详情/整体更新/删除 |
| POST | `/api/v1/teams/{id}/toggle` | 启停用 |
| POST | `/api/v1/teams/{id}/resolve` | body `{query?, mode?}`；返回 `ResolveOut` |

### 3.7 修改 `backend/app/api/v1/skills.py`

现有接口保留（前端在用）。新增：

| 方法 | 路径 | 注意 |
| --- | --- | --- |
| POST | `/api/v1/skills` | 201；`Content-Type: application/json` |
| PUT | `/api/v1/skills/{name}` | 内置 403 |
| POST | `/api/v1/skills/{name}/toggle` | `{enabled: bool}` |
| DELETE | `/api/v1/skills/{name}` | 软删除，返回 `{trash_path}` |
| GET | `/api/v1/skills/{name}/export` | `FileResponse`/`StreamingResponse` + `Content-Disposition` |
| POST | `/api/v1/skills/import` | `UploadFile`，`overwrite` 查询参数 |

**路由顺序坑**：`POST /skills/import` 必须声明在 `POST /skills/{name}/validate` 之前不影响（路径段不同），但 `GET /skills/{name}` 会吞掉 `GET /skills/export` 这类单段路径——因此导出使用 `/{name}/export`，避免冲突。

### 3.8 修改 `run_executor.py` / `agent_service.py`

- `RunExecutor` 解析 `team_id`：`team_service.resolve(team_id, query=prompt, mode=mode)` → `skills` 列表 + `team` 元数据；
- 传 `AgentService.stream(..., team=team, skills=resolved_names)`；
- SSE meta 增加 `team: {id, name, strategy}` 与 `resolved_skills`；
- `skills` 与 `team_id` 同传 → 422（在 schema 层用 `model_validator` 实现，便于前端早期发现）。

### 3.9 启动同步

`lifespan`：`run_migrations()` → `init_app_state()` → `skill_manager.reload()` → `skill_manager.sync_to_db()`（返回孤儿引用告警并打印）。同步失败不阻塞启动，但健康接口暴露 `skill_sync_status`。

---

## 4. 测试计划

### 4.1 Skill 管理（`test_skill_admin.py`）

| 用例 | 断言 |
| --- | --- |
| 创建 | 文件写入 custom 目录，DB 有记录，`GET /skills` 可见，`source=custom` |
| 非法名 | 大写/下划线/超 64 → 422 |
| 同名内置 | 创建 → 409 |
| 编辑内置 | 403 |
| 编辑自定义 | 文件内容更新，mtime 变化 |
| 启停用 | `enabled=false` 后 `resolve_selection` 默认不含；显式传入时被剔除并 warning |
| 软删除 | 目录进入 `.trash`，`GET /skills` 不再返回，可手工恢复 |
| 双目录覆盖 | custom 与 builtin 同名 → list 中只有 custom，`source=custom` |
| 导出 | zip 含 SKILL.md 与资源，不含 `__pycache__` |
| 导入正常 | 解压后 Skill 可用；带一层顶层目录也可 |
| 导入非法 | 缺 SKILL.md / 含 `../` / 绝对路径 / 超 500 文件 / 超 20MB → 422 |
| 导入冲突 | 同名内置 409；同名 custom 且 `overwrite=false` → 409 |
| 同步 | 手工删 custom 目录后 reload+sync → DB 标记 stale，团队 resolve 有 warning |

### 4.2 团队（`test_teams.py`）

| 用例 | 断言 |
| --- | --- |
| CRUD | 创建/详情/更新/删除，成员位置保持 |
| 重名 | 409 |
| 未知成员 | 422；成员去重 |
| 引用计数 | 两个会话绑定后 `reference_count=2` |
| 删除团队 | 成员级联删除；`sessions.team_id` 变 NULL |
| strategy=none | resolve 返回全部启用成员 |
| sequential | `step_index` 按 position 递增；prompt 预览含 `[步骤 1/2]` |
| router | fake LLM 返回 `["pdf"]` → 仅 1 个成员；返回幻觉名 → 求交后为空 + degraded |
| router 降级 | LLM 超时/异常 → `degraded=true`，成员为全量 |
| router 缓存 | 同 query 第二次不调 LLM（fake 调用计数=1） |
| 禁用成员 | resolve 剔除并含 warnings |
| 空团队 | 创建时 `skill_names=[]` → 422（schema 约束）；成员全禁用 → resolve 空 + warning，run 仍可执行 |

### 4.3 集成（`test_team_run.py`）

- 建团队（pdf + data-analysis，sequential）→ 创建 work 会话绑定 → `/agent/run` → 断言：
  - 请求体 `skills` 为展开后的两个名称；
  - system prompt 含团队名与步骤标注；
  - SSE meta 含 `team` 与 `resolved_skills`；
  - `skills` 与 `team_id` 同传 → 422。
- chat 会话绑定团队 → 工具档案仍为只读（团队不提权）。

### 4.4 前端（阶段 2 仅冒烟）

SkillsView：创建/编辑/启停用/导出按钮可用；TeamsView：创建 sequential 团队后 resolve 预览顺序正确；构建通过。

### 4.5 验收标准（DoD）

- [ ] 不改文件系统即可完成 Skill 全生命周期管理；
- [ ] 内置 Skill 不可删改，但可禁用；
- [ ] 三种策略可用，router 有缓存与降级；
- [ ] team/skills 互斥在 schema 层拦截；
- [ ] 导入 zip 通过全部安全用例（穿越/超大/超量/冲突）；
- [ ] 新增测试 ≥ 25 条，原测试全绿。
