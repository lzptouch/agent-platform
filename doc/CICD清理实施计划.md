# Agent Platform · CI/CD 及配套 DevOps 内容移除实施计划

| 项目 | 内容 |
| --- | --- |
| 版本 | v1.2（已复核修订） |
| 编制日期 | 2026-10-18 |
| 目标目录 | `/Users/lizhipeng/workspace/project/agent-platform` |
| 当前状态 | ✅ **已执行完毕**（2026-10-18）。`devops/` 已删除，文档已裁剪，功能回归通过。本文档转为执行留痕 |
| 备份策略 | **不做备份**（用户 2026-10-18 确认），删除不可逆 |
| 核心结论 | `devops/` 74 个文件无任何代码依赖，可整体移除；但**存在 1 个孤儿应用组件（`backend/app/workers/queue_worker.py`）**需一并决策 |

### 修订记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-10-18 | 初稿（方案 A/B/C + 6 阶段） |
| v1.1 | 2026-10-18 | 按用户要求移除备份环节，改为阶段 0 范围终检 |
| v1.2 | 2026-10-18 | 执行前复核：修正 6 处事实性错误、补 3 处逻辑缺口（详见 §0） |

---

## 〇、计划合理性复核结论

复核方式：对照真实仓库逐条验证计划中的事实性断言（文件数、引用数、行号、依赖关系）。

### 总体评价

**删除范围判断成立**：`devops/` 74 个文件对 `backend/`、`frontend/`、`docker-compose.yml`、`deploy/` 均为零依赖，整目录移除不会破坏应用本体与容器化部署；保留 `docker-compose.yml` + `deploy/` 的边界划分正确。

### 发现的问题与处置

| 编号 | 类型 | 问题 | 处置 |
| --- | --- | --- | --- |
| P1 | **事实错误** | 阶段 5 校验命令 `grep -rn "devops/" .` 会命中本计划文档自身（59 处），导致校验**永远不通过** | 校验命令排除计划文档；并新增阶段 7 归档该文档 |
| P2 | **事实错误** | 阶段 3 要求修改 `doc/analysis/05/06/08`，但三篇文档**全文不含 `devops` 字样**，无需任何改动 | 删除这 3 行，改为「无需改动」说明 |
| P3 | **事实错误** | 阶段 3 称 `07_故障排查手册.md` 第二章「保留属于应用镜像构建的部分」，实际该章 9 行内容**全部**是本地 registry/Harbor（8082）排错 | 改为整章删除 |
| P4 | **事实错误** | 称 `frontend/docs/EXECUTION_REPORT.md` 有 2 处引用（537/542），实际有 **4 处**（537、542、552、666） | 补全行号 |
| P5 | **重大遗漏** | `backend/app/workers/queue_worker.py` 是真实应用组件，依赖 Redis，其**唯一部署清单**是 `devops/k8s/optional/worker-deployment.yaml`，Redis 实例由 `devops/infra` 提供。删除后该组件变成不可运行的孤儿代码 | 新增 §3.5 与决策项 D1，纳入 §2.2 方案选择 |
| P6 | **遗漏** | 未处置本计划文档自身（删除后仍 59 处描述已删内容） | 新增阶段 7 |
| P7 | 判定不严谨 | 把 `concurrency/*.py`、`observability/app_instrumentation.py` 归为「配套 DevOps」，二者实为**应用层参考实现**，不属 CI/CD | 重新分类为「非 CI/CD，随目录删除」，并提示可单独保留 |
| P8 | 表述不准 | §2.1 写「`doc/deployment/02~08` 逐篇对应被删目录」，实际 07 是裁剪保留 | 改为「02~06、08 整篇删除；07 裁剪保留」 |
| P9 | 评价过绝对 | 方案 B 称「K8s 与监控实际不可用」，实际仍可手工 `kubectl` 使用，只是失去流水线驱动 | 改为「可手工使用，但需自建发布流程」 |
| P10 | 逻辑缺口 | 未说明删除后「如何交付/发布」，评审方无法判断工程能力损失 | 新增 §1.4 删除后的交付方式 |
| P11 | 提示缺失 | 上一轮镜像版本对齐中，`devops/observability/docker-compose.yml`（prometheus）的修改将随删除失效 | 在 §3.4 加一句说明，避免误判为回退 |

> 以下正文已按上表修订，可直接作为执行依据。

---

## 一、背景与目标

### 1.1 背景

项目当前包含两条相互独立的技术线：

- **应用线**：`backend/` + `frontend/` + `docker-compose.yml` + `deploy/` —— Agent 平台本体及其容器化运行形态
- **工程线**：`devops/` —— 自建 CI/CD 与全套 DevOps 工程（Gitea / Jenkins / Harbor / Registry、K8s 编排、可观测性栈、高并发代码层、压测与 CI 验证记录），配套文档 `doc/deployment/02~06、08` 及 `07` 的相关章节

现需移除工程线，只保留应用线。

### 1.2 目标

1. 删除项目中所有 CI/CD 及配套 DevOps（基础设施 / K8s 编排 / 可观测性 / 压测验证）相关文件
2. 保证删除后应用本体功能完整：`backend` 可启动、`frontend` 可构建、容器化部署可用
3. 清理所有指向已删除文件的悬空文档引用，文档索引无断链

> **删除不可逆**：本项目不受 Git 管理，且已确认不做备份。执行前需确认范围无误，一次性删除。

### 1.3 明确不做的事

| 不做项 | 原因 |
| --- | --- |
| 不改动 `backend/`、`frontend/` 任何业务代码 | 已核验零引用 devops（见 §3.4），无需改动 |
| 不删除 `docker-compose.yml` 与 `deploy/` | 这是**应用自身的运行形态**，不是 CI/CD；删除后应用无法容器化部署 |
| 不修改任何镜像版本 | 上一轮已对齐的 `python:3.12-slim` / `node:22-alpine` / `nginx:1.27-alpine` 等保持不变 |
| 不清理宿主机其他项目的容器 | Docker 环境检查显示本项目相关容器/卷/网络均为空，无需干预 |

### 1.4 删除后的交付方式（能力边界）

| 能力 | 删除前 | 删除后 |
| --- | --- | --- |
| 构建镜像 | Jenkins 流水线自动构建 + Harbor 推送 | **手工** `docker compose build`（本地构建） |
| 发布 | Jenkins → kubectl/kustomize 多环境 | **手工** `docker compose up -d`（单机） |
| 回滚 | 按不可变 tag 回滚 | 重新 build + up；镜像 tag 需自行保留，否则无法回滚 |
| 多环境 | dev / test / prod 三套 overlay | **无**，仅单机单环境 |
| 监控告警 | Prometheus + Grafana + Alertmanager | **无**，仅容器健康检查 + 应用日志 |
| 性能基线 | k6 压测脚本 + 报告 | **无** |

> 结论：删除后项目退化为「源码 + 单机 Docker Compose」形态，符合「只保留应用线」的目标；若后续仍需 CI，应改用外部托管方案（GitHub Actions 等），不在本计划范围。

---

## 二、范围界定

### 2.1 判定标准

| 判定项 | 归属 | 理由 |
| --- | --- | --- |
| Gitea / Jenkins / Harbor / Registry / PostgreSQL / Redis / MinIO 的 Compose 与配置 | **CI/CD** | 自建代码托管 + CI 引擎 + 镜像仓库，是流水线的三件套 |
| `Jenkinsfile`、`pipeline.sh`、`deploy.compose*.yml` | **CI/CD** | 流水线定义与部署目标编排 |
| K8s 清单（base / overlays / optional）、kustomize | **CI/CD** | 由流水线 `kubectl apply` 阶段消费，属发布通道 |
| Prometheus / Loki / Tempo / OTel / Grafana / Alertmanager 全套配置 | **配套 DevOps** | 发布后监控，与流水线强绑定 |
| `devops/concurrency/*.py`（缓存 / 限流 / 异步队列 / 连接池） | **非 CI/CD，但随目录删除** | 这是**应用层参考实现**，不属于 CI/CD；未被应用引用，且应用自身并发实现在 `backend/app/` 内。若希望保留可单独抽出，见决策项 D2 |
| `devops/tests/**`（CI 验证记录、压测脚本与报告） | **配套 DevOps** | 流水线演练产物与性能测试基线 |
| `doc/deployment/02~06、08` | **CI/CD 文档** | 6 篇整篇删除，逐篇对应上述被删目录 |
| `doc/deployment/07_故障排查手册.md` | **裁剪保留** | 仅保留应用容器化排错部分（第一、八章），其余章节随 devops 删除 |
| `doc/deployment/00_导览与总览.md` | **裁剪保留** | 索引与文件地图需重写 |
| `docker-compose.yml`、`deploy/**`、各级 `Dockerfile`、`.dockerignore` | **保留（应用运行）** | 应用自身的构建与运行编排 |
| `doc/analysis/**`、`doc/knowledge/**`、`backend/tests/**` | **保留** | 应用架构 / 原理 / 单元测试，与 CI/CD 无关；经核验均不含 `devops` 引用 |
| `devops/observability/app_instrumentation.py` | **随目录删除** | 应用埋点参考副本（非 CI/CD）；`backend/app/observability.py` 不存在，应用未引用 |

### 2.2 三档范围方案

| 方案 | 删除范围 | 剩余可用性 | 评价 |
| --- | --- | --- | --- |
| **A（推荐，默认执行）** | `devops/` 全目录（74 文件）+ `doc/deployment/02~06、08` + 相关引用清理 | 应用本体 + 容器化部署完整 | 边界清晰，无残留悬空技术债 |
| B（保守） | 仅 `devops/ci`、`devops/infra`、`devops/tests/01-cicd` + `doc/deployment/02/03/04` | 保留 K8s / 可观测性 / 压测 | K8s 与监控仍可手工 `kubectl` / `compose` 使用，但失去流水线驱动，需自建发布流程；保留目录无人维护，易腐化 |
| C（激进） | A + `docker-compose.yml`、`deploy/`、`.dockerignore` | 仅剩源码，需本机 Python / Node 直启 | 应用丧失容器化部署能力，**不推荐** |

> **待确认项**：本计划按方案 A 编制。若需扩大或收窄范围，在评审阶段调整本节即可，下游步骤无需重写。

### 2.3 需一并决策的 3 个附加项

| 编号 | 决策项 | 背景 | 推荐 |
| --- | --- | --- | --- |
| **D1** | `backend/app/workers/queue_worker.py` 如何处理 | 该文件是应用代码，通过 `REDIS_URL` 消费队列；但根 `docker-compose.yml` **不含 redis 与 worker 服务**，其唯一部署清单 `devops/k8s/optional/worker-deployment.yaml` 与 Redis 实例 `devops/infra` 均在删除范围内 → 删除后成为不可运行的孤儿组件 | **保留代码**（不删业务代码，符合 §1.3）；在文件头加一行「当前无部署编排，需外部提供 Redis」说明。若确定不再使用队列，改为删除该文件 |
| **D2** | `devops/concurrency/*.py` 是否保留 | 4 个文件是缓存/限流/队列/连接池的参考实现，非 CI/CD | 随目录删除；如希望留作教材，先复制到 `backend/app/core/` 或独立目录再删 |
| **D3** | `devops/k8s/optional/agent-canary.yaml` 金丝雀方案 | 纯发布策略，无应用价值 | 随目录删除 |

> D1 是本计划唯一的**功能性**决策项，其余为内容取舍。执行前需明确 D1 选择。

---

## 三、现状盘点

### 3.1 `devops/` 目录明细

| 子目录 | 文件数 | 体积 | 内容 | 处置 |
| --- | ---: | ---: | --- | --- |
| `devops/ci/` | 6 | 52K | `Jenkinsfile`、`pipeline.sh`、`deploy.compose.yml`、`deploy.compose.broken.yml`、`nginx-tuned.conf`、`nginx-broken.conf` | 整删 |
| `devops/infra/` | 11 | 52K | `docker-compose.yml`、`.env.example`、`harbor/`(3)、`jenkins/`(3)、`nginx/`(1)、`postgres/`(1)、`registry/`(1) | 整删 |
| `devops/k8s/` | 17 | 88K | `base/`(8)、`overlays/{dev,test,prod}`(6)、`optional/`(3) | 整删 |
| `devops/observability/` | 14 | 64K | Prometheus / Alertmanager / Grafana / Loki / Tempo / OTel 配置 + `app_instrumentation.py` + `k8s/` values | 整删 |
| `devops/concurrency/` | 4 | 32K | `cache.py`、`rate_limit.py`、`async_queue.py`、`pools.py` | 整删 |
| `devops/tests/` | 18 | 180K | `01-cicd/`(6)、`02-stress/`(10)、`03-devops-stack/`(1)、`04-k8s/`(1) | 整删 |
| 根级文档 | 4 | — | `README.md`、`ARCHITECTURE.md`、`README.pdf`、`ARCHITECTURE.pdf` | 整删 |
| **合计** | **74** | **5.9M** | — | — |

> 注意：`devops/infra/registry/htpasswd` 为 Registry 认证文件、`devops/infra/.env.example` 为口令模板。因不做备份，这两个文件将随目录一并永久删除；若其中含仍在使用的口令，需在删除前另行留存（口令本身建议在宿主机密码管理器中重建，而非保留文件）。

### 3.2 文档侧引用统计

全项目文档中共 **146 处** `devops/` 路径引用，分布于 12 个文件：

| 文件 | 引用数 | 处置 |
| --- | ---: | --- |
| `doc/deployment/08_脚本资产与端到端复现.md` | 32 | 整篇删除 |
| `doc/deployment/00_导览与总览.md` | 14 | **裁剪重写**（含全局文件地图与组件表） |
| `doc/deployment/01_基础设施与Compose编排.md` | 13 | 整篇删除 |
| `doc/deployment/03_Jenkins与配置即代码.md` | 11 | 整篇删除 |
| `doc/deployment/04_CI流水线原理与实现.md` | 10 | 整篇删除 |
| `doc/deployment/05_Kubernetes编排与发布.md` | 10 | 整篇删除 |
| `doc/deployment/02_Harbor私有仓库部署.md` | 8 | 整篇删除 |
| `doc/deployment/06_可观测性栈与统一门户.md` | 8 | 整篇删除 |
| `doc/README.md` | 4 | 改写（文档清单表 + 阅读顺序 + 统计数字） |
| `doc/deployment/07_故障排查手册.md` | 3 | **裁剪**（删除第三~七章与附录引用，保留容器/镜像/Windows 排查） |
| `frontend/docs/EXECUTION_REPORT.md` | 2 路径 + 2 叙述 | 修改 4 处：537 行「`devops/` 下已有 14 个 DevOps 容器运行」、542 行「参考 `devops/ci/pipeline.sh`」、552 行 `docker push devops-harbor:8082/...`、666 行标题「Docker 部署（devops 链已就绪）」 |
| `部署文件分析与操作手册.md`（根，46KB） | 31 | **裁剪重写**（删第 2/3 层结构与 DevOps 操作章节） |
| `部署文件分析与操作手册_tmp.html` | 31 | 与 `.md` 同步处理，或直接删除（临时产物） |

> 合计 146 处仅统计 `devops/` 路径形式；若含裸词 `devops`（如「devops 链」），总提及为 300 处（含本计划文档 59 处）。

### 3.3 依赖关系核验结论

| 核验项 | 方法 | 结果 |
| --- | --- | --- |
| 后端代码是否引用 devops | `grep -rn "devops" backend --include=*.py/*.md/*.txt/*.toml` | **0 命中**，无依赖 |
| 应用是否引用 `devops/concurrency` 模块 | 检索 `from devops` / `import devops` / `concurrency.*` | **0 命中**，无依赖 |
| 应用是否引用 `devops/observability/app_instrumentation.py` | 检索 `observability` / `app_instrumentation` | 仅该文件自身注释命中，`backend/app/observability.py` **不存在**，从未被引用 |
| 构建上下文是否含 devops | 检查 `.dockerignore` | **未排除** devops → 删除后 build context 减少约 5.9M，无需修改 `.dockerignore` |
| 本项目 Docker 资源是否在用 | `docker ps -a` / `volume ls` / `network ls` 过滤 `agent\|devops\|obs-` | 容器 / 卷 / 网络 **均为空**，无需 `compose down` |

### 3.4 `devops/k8s` 镜像引用说明

`devops/k8s/**` 中的 `image:` 全部指向**本项目自建镜像名**（`agent-platform-backend:1.1.0`、`agent-platform-web:1.1.0`、`harbor.local/agent/agent-platform-backend:1.1.0-canary`、`registry.infra.svc.cluster.local:5000/agent/...`），与基础镜像基线无关，随目录一并删除即可，不影响上一轮的镜像版本对齐结果。

> 补充：上一轮镜像对齐共 6 处修改，其中 **1 处位于 `devops/observability/docker-compose.yml`（prom/prometheus v2.53.0）将随删除一并消失**；其余 5 处（`backend/Dockerfile`、`deploy/backend/Dockerfile`、`deploy/frontend/Dockerfile`、`deploy/docker-compose.milvus.yml`×2）保留，属预期行为，不是版本回退。

### 3.5 删除后失效的活跃应用组件（关键）

| 组件 | 位置 | 依赖的 devops 资源 | 删除后状态 |
| --- | --- | --- | --- |
| 队列 Worker | `backend/app/workers/queue_worker.py` | ① Redis 实例：`devops/infra/docker-compose.yml`<br>② 部署清单：`devops/k8s/optional/worker-deployment.yaml` | **不可运行**：根 `docker-compose.yml` 只有 `backend` + `web`，无 redis、无 worker 服务；`REDIS_URL` 默认 `redis://127.0.0.1:6379/0` 无服务监听 |

核验依据：

- `backend/app/workers/queue_worker.py` 通过标准库实现最小 RESP 客户端，消费 `REDIS_URL`
- 根 `docker-compose.yml` 的 `services:` **仅 2 个**：`backend`、`web`，无 redis / worker
- `grep -rn "queue_worker" backend/app` → 除自身外**无任何引用**，说明主应用不会 import 它，删除 devops 不会导致启动报错，但该组件永久失去运行条件

> 该文件**不属于 CI/CD**，可以保留（仅成为休眠代码），也可一并删除。见决策项 D1。

---

## 四、影响面分析

| 影响面 | 影响 | 处置 |
| --- | --- | --- |
| 应用运行 | **无**。`backend` / `frontend` / `docker-compose.yml` / `deploy/` 均不引用 devops（已逐文件核验） | 无需动作 |
| 队列 Worker | `backend/app/workers/queue_worker.py` 失去 Redis 与部署清单，**变为不可运行**；因其未被主应用 import，不影响启动 | 决策 D1：保留代码并加注说明，或一并删除 |
| 容器化构建 | 构建上下文减小 ~5.9M；`COPY` 路径不受影响（已核验：`deploy/backend/Dockerfile` 只 COPY `backend/{app,skills,scripts,requirements.txt,pyproject.toml,conftest.py}` 与 `deploy/backend/entrypoint.sh`；前端只 COPY `frontend/${FRONTEND_APP}` 与 `deploy/nginx/**`，**无 `COPY . .`**） | 无需动作 |
| 应用镜像版本 | 不涉及基础镜像改动；仅 prometheus 那 1 处在删除范围内失效 | 见 §3.4 说明 |
| 交付与发布能力 | 失去 CI 自动构建、多环境 K8s 发布、按 tag 回滚、监控告警、压测基线 | 见 §1.4，接受退化为单机 Compose 形态 |
| 镜像回滚能力 | 根 `docker-compose.yml` 用固定 tag（`1.1.0`），删除 Harbor 后无镜像仓库，旧镜像只存在于本机 | 发布前自行 `docker tag` 备份目标镜像 |
| 文档索引 | `doc/README.md`、`doc/deployment/00` 出现断链（指向已删文件） | 阶段 3 处理 |
| 悬空引用 | 保留文档中残留 146 处路径引用 | 阶段 3 处理 |
| Docker 宿主机环境 | 无本项目容器 / 卷 / 网络 | 无需动作 |
| 团队协作 | 若他人在使用 Jenkins（8081）/ Harbor（8082）/ Gitea（3000）控制台，需提前通知 | **前置动作**，见 §7 风险 R3 |

---

## 五、实施步骤

### 阶段 0：范围终检（执行前一次性确认）

> 本项目不受 Git 管理（已核验 `.git` 不存在），且已确认**不做备份**，删除不可逆。
> 本阶段替代备份环节：执行前用下列命令核对删除清单，确认与预期一致后立即进入阶段 1。

```bash
cd /Users/lizhipeng/workspace/project/agent-platform

# 确认待删目录存在、文件数与预期一致（devops 应为 74）
find devops -type f | wc -l
du -sh devops

# 确认应用运行编排「不在」删除范围内（下列文件必须存在）
ls docker-compose.yml .dockerignore \
   deploy/backend/Dockerfile deploy/frontend/Dockerfile \
   deploy/backend/entrypoint.sh deploy/nginx/nginx.conf \
   deploy/docker-compose.milvus.yml

# 确认应用代码「零引用」devops（应无输出）
grep -rn "devops/" backend frontend --exclude-dir=node_modules --exclude-dir=.venv \
     --exclude-dir=__pycache__ | head
```

**通过标准**：
1. 文件数 = 74
2. 应用编排文件全部存在
3. 应用代码无 devops 引用
4. **决策项 D1 已确认**（`queue_worker.py` 保留加注 / 一并删除）
5. **决策项 D2 已确认**（`concurrency/*.py` 是否先另存）

前 3 项全绿、后 2 项有明确结论，方可执行阶段 1。

### 阶段 1：删除 `devops/` 全目录

```bash
cd /Users/lizhipeng/workspace/project/agent-platform

# 删除前二次确认存在性
ls -d devops && find devops -type f | wc -l

rm -rf devops

# 校验
test -d devops && echo "删除失败" || echo "devops 已移除"
```

> 若采用方案 B，则本阶段改为按目录粒度删除 `devops/ci`、`devops/infra`、`devops/tests/01-cicd`，保留 `k8s/`、`observability/`、`concurrency/`、`tests/02~04`，并同步执行 §3.2 的文档删除子集。

### 阶段 2：删除 CI/CD 主题文档

```bash
cd /Users/lizhipeng/workspace/project/agent-platform/doc/deployment

rm -f 01_基础设施与Compose编排.md \
      02_Harbor私有仓库部署.md \
      03_Jenkins与配置即代码.md \
      04_CI流水线原理与实现.md \
      05_Kubernetes编排与发布.md \
      06_可观测性栈与统一门户.md \
      08_脚本资产与端到端复现.md

ls    # 应仅剩 00_导览与总览.md、07_故障排查手册.md
```

### 阶段 3：裁剪与改写保留文档

| 文件 | 具体动作 |
| --- | --- |
| `doc/README.md` | ① 删除清单表中 deployment 02~06、08 各行<br>② 重写「DevOps / 运维」阅读顺序条目（改为指向 `deploy/README.md`）<br>③ 更新「总计」统计（原 26 篇 → 实际剩余篇数）<br>④ 更新「与现有 doc/ 关系」中关于 `devops/**` 的分工说明<br>⑤ 更新「版本信息」中对 `devops/**` 的描述 |
| `doc/deployment/00_导览与总览.md` | ① 文件地图删除 `devops/**` 全部条目<br>② 组件与端口表删除 Jenkins / Gitea / Harbor / Registry / Prometheus / Grafana / Alertmanager 等行<br>③ 快速开始只保留应用三步启动（构建 → 启动 → 访问 8080）<br>④ 章节重编号，保持目录锚点连续 |
| `doc/deployment/07_故障排查手册.md` | ① **删除第二章整章**（经核验 9 行内容全部是本地 registry:8082 / Harbor 排错：`credsStore`、`docker login 401`、`[::1]` 超时、`insecure-registries`、`htpasswd` 占位哈希等），同时删除第三~七章<br>② 仅保留第一章（容器与编排）、第八章（Windows/Git Bash）<br>③ 第九章体检脚本改为仅体检应用编排<br>④ 附录 A 检索表删除指向 `devops/tests/*`、`devops/ARCHITECTURE.md` 的条目<br>⑤ 章节重编号 |
| `doc/analysis/05_可观测体系设计.md` | **无需改动**：经核验全文不含 `devops` 字样，是自包含的设计建议文档 |
| `doc/analysis/06_高并发.md` | **无需改动**：经核验全文不含 `devops` 字样，应用并发实现位于 `backend/app/`，与被删目录无关 |
| `doc/analysis/08_测试体系.md` | **无需改动**：经核验全文不含 `devops` 字样，测试基线对应 `backend/tests/` |
| `frontend/docs/EXECUTION_REPORT.md` | 修改 **4 处**：537 行「`devops/` 下已有 14 个 DevOps 容器运行」、542 行「参考 `devops/ci/pipeline.sh`」、552 行 `docker push devops-harbor:8082/...`、666 行标题「Docker 部署（devops 链已就绪）」，统一改为说明 CI/CD 已移除 |
| `backend/app/workers/queue_worker.py` | 仅当 D1 选择「保留」时执行：在文件头 docstring 增加一行「当前仓库无 Redis 与 worker 部署编排，需外部提供 Redis；K8s 清单已随 CI/CD 清理移除」 |

### 阶段 4：根级部署手册处置

`部署文件分析与操作手册.md`（46KB，31 处引用）内容为「三层部署结构」全景，需裁剪为「单层（应用容器化）」：

1. 第 8~9 行 分析基准声明：删除 `devops/**`、`devops/README.md`、`devops/ARCHITECTURE.md`、`doc/deployment/**` 引用
2. 第二章「部署文件全景：三层结构」→ 改为两层（保留根 `docker-compose.yml` + `deploy/`）
3. 第三章层级结构树：删除 `devops/**` 整块
4. 第四章运行时架构：删除三环境矩阵（引用 `devops/ARCHITECTURE.md` §7）
5. 第六章操作步骤：删除 Gitea 建仓推送、Jenkins 触发、Harbor 安装、K8s 部署命令段（对应 429~582 行区间）
6. 目录（14~37 行）与「结论速览」表格同步更新
7. `部署文件分析与操作手册_tmp.html`：建议**直接删除**（由 Markdown 生成的临时预览产物，无独立信息）；若需保留则须与 `.md` 同步重生成

### 阶段 5：一致性校验

```bash
cd /Users/lizhipeng/workspace/project/agent-platform

# 1) 不应再有 devops 目录
test -d devops && echo "❌ devops 仍存在" || echo "✅ devops 已移除"

# 2) 全项目不应再有 devops 引用
#    ⚠ 必须排除本计划文档，否则会命中自身 59 处，校验永远不通过
grep -rn "devops/" . \
     --exclude-dir=node_modules --exclude-dir=.venv \
     --exclude-dir=__pycache__ --exclude-dir=.pytest_cache \
     --exclude="CICD清理实施计划.md" | head -20
# 期望：无输出

# 3) 文档内不应再有指向已删文件的链接
grep -rn "deployment/0[1-8]" doc/ --exclude="CICD清理实施计划.md" | head -20
# 期望：无输出（00 与 07 两个保留文件不应引用已删篇目）

# 4) 应用核心文件完好
ls docker-compose.yml deploy/backend/Dockerfile deploy/frontend/Dockerfile \
   deploy/nginx/nginx.conf deploy/backend/entrypoint.sh

# 5) D1 处置结果确认
grep -n "Redis" backend/app/workers/queue_worker.py | head -3
#    - 选择保留：文件存在，且 docstring 已加注说明
#    - 选择删除：文件不存在
test -f backend/app/workers/queue_worker.py && echo "worker 保留" || echo "worker 已删除"
```

### 阶段 6：功能回归验证

```bash
cd /Users/lizhipeng/workspace/project/agent-platform

# ① 编排文件语法校验
docker compose config --quiet && echo "✅ compose 配置有效"

# ② 后端单元测试
cd backend && .venv/bin/python -m pytest tests/ -q    # 期望 40 passed
cd ..

# ③ 镜像构建（验证删除 devops 未破坏构建上下文）
docker compose build

# ④ 端到端启动
cp -n backend/.env.example backend/.env 2>/dev/null   # 已存在则跳过
docker compose up -d
docker compose ps                                    # backend / web 均 healthy
curl -fsS http://127.0.0.1:8080/api/v1/health        # 期望 200
curl -fsSI http://127.0.0.1:8080/ | head -1           # 期望 HTTP/1.1 200

# ⑤ 收尾
docker compose down
```

> 说明：`docker compose build` 若保持 `INSTALL_PLAYWRIGHT=true`（默认），需下载 Chromium，耗时可达 10 分钟以上。快速验证可改用 `INSTALL_PLAYWRIGHT=false docker compose build`，但小红书 MCP 相关功能将不可用。

### 阶段 7：归档本计划文档

本计划文档自身包含 **59 处 `devops/` 引用**，执行完成后会成为全项目最后一批「指向已删内容」的文本。

| 选项 | 做法 | 适用 |
| --- | --- | --- |
| **A（推荐）** | 保留在 `doc/`，在文首加一行「本文档为历史执行记录，所述 `devops/` 已移除」 | 需要留痕、复盘 |
| B | 移动到项目外（如 `~/workspace/_archive/`） | 不希望污染项目文档集 |
| C | 直接删除 | 只要结果，不要过程 |

> 若选择 A，阶段 5 的校验命令必须持续保留 `--exclude="CICD清理实施计划.md"`，否则校验会命中本文档。

---

## 六、风险登记与应对

| 编号 | 风险 | 等级 | 应对 |
| --- | --- | --- | --- |
| R1 | **无 Git 版本控制 + 不做备份，删除不可逆** | 高 | 已确认接受该风险。以阶段 0 的范围终检作为唯一防线：文件数须为 74、应用编排文件须齐全、应用代码零引用（前三项全绿），且 D1/D2 决策已确认，方可执行 `rm -rf` |
| R2 | 文档裁剪不彻底，残留断链 | 中 | 阶段 5 校验命令固化为必过项；断链数必须为 0 才算完成 |
| R3 | 团队成员仍在使用 Jenkins / Harbor 控制台 | 中 | 删除前 1 个工作日通知；确认无活跃流水线作业与保留镜像 |
| R4 | 误删应用运行编排 | 中 | §1.3 与 §2.1 已明确 `deploy/`、`docker-compose.yml` 为保留项；阶段 0 与阶段 6 双重覆盖 |
| R5 | 根级部署手册裁剪工作量大（46KB / 31 处引用） | 低 | 可分两次执行：先删 devops 与专题文档，手册裁剪作为独立子任务排期 |
| R6 | **校验命令自我命中**，导致阶段 5 永远无法通过、误判删除不彻底 | 中 | 校验命令已加 `--exclude="CICD清理实施计划.md"`；若后续把该文档改名，需同步更新排除规则 |
| R7 | `queue_worker.py` 保留后长期无人维护，形成「有代码无编排」的僵尸组件 | 低 | 已通过 §3.5 与 D1 显式记录；建议在组件 README 或文件头注明运行前提 |
| R8 | 删除 Harbor 后无镜像仓库，旧版本镜像只存在于本机，误删即永久丢失 | 中 | 发布前 `docker tag agent-platform-backend:1.1.0 agent-platform-backend:1.1.0-bak` 本地留底 |

---

## 七、验收标准

删除完成后，以下条件全部满足即视为通过：

- [ ] `devops/` 目录不存在（删除前记录的文件数为 74）
- [ ] `doc/deployment/` 仅剩 `00_导览与总览.md` 与 `07_故障排查手册.md`，且目录索引无断链
- [ ] 全项目 `grep "devops/"`（排除本计划文档）**无输出**
- [ ] `doc/deployment/07` 第二章（本地 registry/Harbor 排错）已整章删除
- [ ] `frontend/docs/EXECUTION_REPORT.md` 4 处 devops 提及（537/542/552/666）已全部改写
- [ ] 决策项 D1 已落实：`queue_worker.py` 或已删除，或已加注运行前提说明
- [ ] 决策项 D2 已落实：`concurrency/*.py` 或已删除，或已另存至保留目录
- [ ] 阶段 7 已执行：本计划文档已归档 / 移动 / 删除，且文首状态与实际一致
- [ ] `docker compose config` 通过
- [ ] `docker compose build` 成功（backend + web）
- [ ] `docker compose up -d` 后 `backend` / `web` 均 healthy，`/api/v1/health` 返回 200
- [ ] `backend` 单元测试 40 passed
- [ ] 镜像版本仍为上一轮对齐结果：`python:3.12-slim`、`node:22-alpine`、`nginx:1.27-alpine`

---

## 八、命令速查附录

```bash
# 执行前终检（不做备份，前 3 项全绿 + D1/D2 有结论方可删除）
cd /Users/lizhipeng/workspace/project/agent-platform
find devops -type f | wc -l                                  # 期望 74
ls docker-compose.yml deploy/backend/Dockerfile deploy/frontend/Dockerfile
grep -rn "devops/" backend frontend --exclude-dir=node_modules \
     --exclude-dir=.venv --exclude-dir=__pycache__ | head    # 期望无输出

# 删除
rm -rf devops
rm -f doc/deployment/{01,02,03,04,05,06,08}_*.md

# 校验（必须排除本计划文档，否则命中自身 59 处）
test -d devops && echo "❌" || echo "✅"
grep -rn "devops/" . --exclude-dir=node_modules --exclude-dir=.venv \
     --exclude="CICD清理实施计划.md" | head                 # 期望无输出
docker compose config --quiet && echo "✅ compose ok"

# 镜像留底（Harbor 删除后无仓库可回溯）
docker tag agent-platform-backend:1.1.0 agent-platform-backend:1.1.0-bak
docker tag agent-platform-web:1.1.0 agent-platform-web:1.1.0-bak
```

---

## 九、执行记录表（已填写）

| 阶段 | 开始时间 | 完成时间 | 结果 | 备注 |
| --- | --- | --- | --- | --- |
| 阶段 0 范围终检 | 2026-10-18 | 2026-10-18 | ✅ | 74 文件、编排齐全、代码零引用；D1=保留加注，D2=随删 |
| 阶段 1 删 devops/ | 2026-10-18 | 2026-10-18 | ✅ | `rm -rf devops`，74 文件 / 5.9M |
| 阶段 2 删 CI/CD 文档 | 2026-10-18 | 2026-10-18 | ✅ | 删除 01~06、08 共 6 篇 + `_tmp.html` |
| 阶段 3 裁剪保留文档 | 2026-10-18 | 2026-10-18 | ✅ | `doc/README.md`、`00_导览`（重写）、`07_手册`（重写）、`EXECUTION_REPORT.md` 4 处、`queue_worker.py` 加注 |
| 阶段 4 根级手册处置 | 2026-10-18 | 2026-10-18 | ✅ | 876→524 行，切除 L2/L3/L4 路线与三层结构 |
| 阶段 5 一致性校验 | 2026-10-18 | 2026-10-18 | ✅ | 仅剩 3 处「已移除」说明性文字；无断链 |
| 阶段 6 功能回归 | 2026-10-18 | 2026-10-18 | ✅ | compose config ok；镜像构建成功；双服务 healthy；4 端点 200；**pytest 40 passed** |
| 阶段 7 归档本计划 | 2026-10-18 | 2026-10-18 | ✅ | 选项 A：保留在 `doc/` 作为执行留痕 |

### 执行期的偏差与说明

| 项 | 说明 |
|---|---|
| **D1 落地** | `backend/app/workers/queue_worker.py` 保留，已在文件头 docstring 加注「当前仓库不提供 Redis 与部署清单」 |
| **本地 venv 失效** | `backend/.venv` 的 python 符号链接指向已删除的 `~/.local/share/uv/python/...`，属既有环境问题（非本次清理造成）。测试改用容器内环境：`docker run --rm --entrypoint python -v "$PWD/backend:/app" -w /app agent-platform-backend:1.1.0 -m pytest -q` |
| **8080/8081 被占用** | 宿主已有其他项目容器占用这两个端口，验证改用 `HOST_HTTP_PORT=18080`；验证结束后已 `down -v` 清理容器与数据卷 |
| **构建参数** | 验证构建用 `INSTALL_PLAYWRIGHT=false` 以缩短耗时；镜像功能正常，仅小红书 MCP 的 Chromium 缺失。生产构建请去掉该参数 |
| **镜像未留底** | 本机原先无应用镜像（`docker images` 为空），故无历史镜像可回滚；本次构建产物 `agent-platform-backend:1.1.0` / `-web:1.1.0` 已保存在本机 |
