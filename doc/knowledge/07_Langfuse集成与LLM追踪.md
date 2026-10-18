# Langfuse 集成与 LLM 追踪（扩充版）

> - **整理日期**：2026-09-15（首发 2026-09-15 扩充）
> - **依据项目**：`agent-platform` 后端 LLM 追踪链路（已集成 Langfuse）
> - **资料来源**：Langfuse 官方文档 + OpenTelemetry 官方 + Arize Phoenix + OpenLLMetry + LangSmith + Helicone

---

# 第一章 LLM 应用可观测的挑战

| 传统 Web 应用 | LLM 应用 |
|--------------|---------|
| 请求响应确定性强 | 输出非确定 |
| 延迟毫秒级 | 延迟秒~分钟 |
| 错误易定位 | 幻觉难发现 |
| 监控 4 个黄金指标足够 | 需追踪 token / prompt / cost |
| 无版本概念 | Prompt 频繁迭代 |

LLM 应用需要**专项可观测工具**：追踪每一次调用的 prompt + completion + token + cost + latency。

---

# 第二章 Langfuse 是什么

[Langfuse](https://langfuse.com) 是开源 LLM 可观测 + 评估平台：

- **Tracing**：记录每次 LLM 调用的输入/输出/元数据
- **Prompt Management**：Prompt 版本化、灰度
- **Evaluation**：人工 + 自动评估
- **Datasets**：测试用例管理

## 与 OpenTelemetry 集成

Langfuse **原生支持 OTel**——可直接用 OpenTelemetry SDK 追踪，自动导出到 Langfuse 后端。

参考：https://langfuse.com/docs/opentelemetry/get-started

---

# 第三章 集成模式

## 3.1 OpenTelemetry SDK + Langfuse Exporter

```python
# utils/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()

# ★ 关键：endpoint 指向 Langfuse
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint=os.getenv("LANGFUSE_OTEL_ENDPOINT", "https://cloud.langfuse.com/api/public/otel"),
    headers={
        "Authorization": f"Basic {base64_encode(f'{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}')}"
    }
)))

trace.set_tracer_provider(provider)
```

## 3.2 自动注入 FastAPI

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()  # ★ DashScope HTTPX 调用自动追踪
```

## 3.3 装饰器追踪特定调用

```python
from langfuse.decorators import observe, langfuse_context

@observe(name="agent_run")
async def stream_agent_run(prompt: str, model: str, **kwargs):
    langfuse_context.update_current_observation(
        input=prompt,
        metadata={"model": model, **kwargs}
    )
    result = await agent_loop(prompt, model, **kwargs)
    langfuse_context.update_current_observation(output=result)
    return result
```

## 3.4 Langfuse Python SDK（原生）

```python
from langfuse import Langfuse

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

# 直接调用
trace = langfuse.trace(name="agent_run", input={"prompt": prompt})
generation = trace.generation(
    name="llm-call",
    model="qwen-max",
    input=prompt,
    output=response,
    usage={"input_tokens": 100, "output_tokens": 200},
)
```

---

# 第四章 业界 LLM 可观测对比

| 平台 | 开源/付费 | OTel | Prompt 版本 | 评估 | 自部署 | 适用 |
|------|----------|------|------------|------|--------|------|
| **Langfuse** | 开源 + SaaS | ✅ | ✅ | ✅ | ✅ | 本项目；通用 |
| **Arize Phoenix** | 开源 | ✅ | ❌ | ✅ | ✅ | 评估为主 |
| **OpenLLMetry** | 开源 | ✅ | ❌ | ❌ | ✅ | 仅追踪 |
| **LangSmith** | 仅 SaaS | ❌ | ✅ | ✅ | ❌ | LangChain 专属 |
| **Helicone** | 开源 + SaaS | ❌ | ✅ | ❌ | ✅ | 简单代理 |
| **DataDog LLM Obs** | 仅 SaaS | ✅ | ❌ | ✅ | ❌ | 企业级 |
| **Portkey** | SaaS | ❌ | ✅ | ❌ | ❌ | 路由 |

**推荐**：本项目用 Langfuse 已合理。

### 4.1 Langfuse vs LangSmith

| 维度 | Langfuse | LangSmith |
|------|----------|-----------|
| 价格 | 免费 tier 慷慨 | 商业付费 |
| 开源 | ✅（自部署） | ❌ |
| Prompt 版本管理 | ✅ | ✅ |
| 评估 | ✅ 内置 | ✅ |
| OTel | ✅ | 部分 |
| 自托管 | ✅ Docker | ❌ |
| UI 美观度 | 中 | 高 |

---

# 第五章 Prompt 版本管理（Langfuse 特色）

## 5.1 从 Langfuse 拉取 Prompt

```python
from langfuse import Langfuse

langfuse = Langfuse()

# 拉取特定版本
prompt_v2 = langfuse.get_prompt("agent-system-prompt", version=2)
system_prompt = prompt_v2.compile(skills=..., mcp_tools=...)

# 拉取最新生产版本
prompt_prod = langfuse.get_prompt("agent-system-prompt", label="production")

# 拉取最新版本（任意环境）
prompt_latest = langfuse.get_prompt("agent-system-prompt")
```

## 5.2 收益

- ✅ Prompt 迭代无需改代码
- ✅ A/B 测试（多版本并行）
- ✅ 灰度发布（label 控制）
- ✅ 版本回滚

## 5.3 本项目应用

```python
# services/agent/skill_manager.py
def build_system_prompt(self, selected_skills: list[str]) -> str:
    """从 Langfuse 拉取系统提示"""
    if langfuse.configured:
        prompt = langfuse.get_prompt("agent-system-prompt", label="production")
        return prompt.compile(skills=selected_skills)
    else:
        # 回退到内置
        return BASE_SYSTEM_PROMPT
```

---

# 第六章 评估（Evaluation）

## 6.1 LLM 评估类型

| 类型 | 方法 | 适用 |
|------|------|------|
| **人工评估** | 用户打分（👍/👎） | 体验反馈 |
| **自动评估** | LLM-as-Judge（用 Claude/GPT 打分） | 质量监控 |
| **启发式评估** | 长度、关键词匹配 | 简单校验 |
| **参考评估** | 与标准答案对比 | 测试用例 |

## 6.2 Langfuse Score 集成

```python
# 人工评估
langfuse.score(
    trace_id=trace.id,
    name="user-feedback",
    value=1,                    # 👍
    comment="回答准确"
)

# 自动评估（LLM-as-Judge）
from langfuse import Langfuse
judge_prompt = f"""评估以下回答的质量（0-1）：

问题：{query}
回答：{answer}

仅返回数字。"""

score_text = await judge_llm.simple_chat(judge_prompt)
langfuse.score(
    trace_id=trace.id,
    name="llm-judge",
    value=float(score_text),
)
```

## 6.3 Datasets（测试用例）

```python
# Langfuse Datasets 管理
dataset = langfuse.create_dataset(name="agent-test")

# 添加测试用例
langfuse.create_dataset_item(
    dataset_name="agent-test",
    input={"query": "贵州茅台财务"},
    expected_output={"intent": "data_query", "tools": ["text2sql"]}
)

# 运行测试
for item in dataset.items:
    result = await agent.run(item.input)
    # 用 expected_output 对比
    score = compare(result, item.expected_output)
    langfuse.score(trace_id=result.trace_id, name="test-pass", value=score)
```

---

# 第七章 本项目实践要点

## 7.1 已实现

| 主题 | 备注 |
|------|------|
| **Langfuse 已集成** | 经主入口观察到 |
| 工具来源标注 | `tool_source: builtin/mcp/rag/web`（App.vue:184） |
| 文件落盘 | `data/outputs/chat_log_*.json`（`agent_service._save_log`） |
| **OTel SDK 注入** | FastAPI + HTTPX 自动埋点 |
| 5 链开关 metadata | 可在 Langfuse Trace 中筛选 |

## 7.2 待改进

| 主题 | 优先级 |
|------|------|
| 完整 Generation 追踪（input/output/token） | P0 |
| Prompt 版本化管理 | P1 |
| 用户反馈打分 UI | P1 |
| 自动 LLM-as-Judge | P2 |
| 数据集回归测试 | P2 |

---

# 第八章 操作步骤

## 8.1 P0-1：完整 Generation 追踪

```python
# services/llm.py
from langfuse.decorators import observe, langfuse_context

class LLMClient:
    @observe(name="llm-chat", as_type="generation")
    def chat(self, messages, model, **kwargs):
        # 记录输入
        langfuse_context.update_current_observation(
            input=messages,
            model=model,
            metadata=kwargs,
        )
        
        # 实际调用
        response = self._do_chat(messages, model, **kwargs)
        
        # 记录输出 + token
        langfuse_context.update_current_observation(
            output=response.choices[0].message.content,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        )
        
        return response
```

## 8.2 P0-2：5 链开关 metadata

```python
# services/agent_service.py
@observe(name="agent_run")
async def stream_loop(prompt, skills, enable_mcp, enable_rag, ...):
    langfuse_context.update_current_observation(
        input={"prompt": prompt},
        metadata={
            "skills": skills,
            "enable_mcp": enable_mcp,
            "enable_rag": enable_rag,
            "enable_web_research": enable_web_research,
            "enable_reflection": enable_reflection,
        }
    )
    # ...
```

## 8.3 P1-1：Prompt 版本管理

```python
# config.py
class Settings(BaseSettings):
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_enabled: bool = False
    
    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key) and bool(self.langfuse_secret_key)

# main.py lifespan
if settings.langfuse_configured:
    init_langfuse(settings)
    logger.info("Langfuse 已启用")
```

## 8.4 P1-2：前端 Sentry（用户错误）

```typescript
// frontend/src/main.ts
import * as Sentry from '@sentry/vue'

if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    app,
    dsn: import.meta.env.VITE_SENTRY_DSN,
    tracesSampleRate: 0.2,
  })
}
```

## 8.5 P2-1：完整接入 Langfuse 配置

```python
# utils/langfuse.py
def init_langfuse(settings):
    """初始化 Langfuse + OTel"""
    if not settings.langfuse_configured:
        logger.info("Langfuse 未配置（PUBLIC_KEY/SECRET_KEY 缺失）")
        return
    
    # 1. 设置环境变量（OTel SDK 使用）
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_OTEL_ENDPOINT"] = f"{settings.langfuse_host}/api/public/otel"
    
    # 2. 初始化 OTel Provider
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(
            endpoint=os.environ["LANGFUSE_OTEL_ENDPOINT"],
            headers={"Authorization": auth_header()}
        ))
    )
    trace.set_tracer_provider(provider)
    
    # 3. 自动注入
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    
    logger.info("Langfuse + OTel 初始化完成")
```

---

## 附录 A：参考文献

| # | 类型 | 标题 | 来源 | 访问日期 |
|---|------|------|------|----------|
| [1] | 官方文档 | Langfuse | https://langfuse.com/docs | 2026-09-15 |
| [2] | 官方文档 | Langfuse OpenTelemetry | https://langfuse.com/docs/opentelemetry/get-started | 2026-09-15 |
| [3] | 官方文档 | Langfuse Python SDK | https://langfuse.com/docs/sdk/python | 2026-09-15 |
| [4] | 官方文档 | Langfuse Prompt Management | https://langfuse.com/docs/prompts | 2026-09-15 |
| [5] | 官方文档 | Langfuse Evaluation | https://langfuse.com/docs/scores | 2026-09-15 |
| [6] | 官方文档 | OpenTelemetry Python | https://opentelemetry.io/docs/languages/python/ | 2026-09-15 |
| [7] | OSS 项目 | Arize Phoenix | https://github.com/Arize-ai/phoenix | 2026-09-15 |
| [8] | OSS 项目 | OpenLLMetry | https://github.com/traceloop/openllmetry | 2026-09-15 |
| [9] | 官方文档 | LangSmith | https://docs.smith.langchain.com | 2026-09-15 |
| [10] | OSS 项目 | Helicone | https://github.com/Helicone/helicone | 2026-09-15 |
| [11] | OSS 项目 | Portkey | https://github.com/Portkey-AI/portkey | 2026-09-15 |
| [12] | 同源文档 | `apps/financial-report-agent/doc/analysis/05_可观测体系设计.md` | 三支柱基础 | 2026-09-15 |
| [13] | 同源文档 | `apps/industry-research-assistant/doc/analysis/05_可观测体系设计.md` | 5 集成监控 | 2026-09-15 |

---

> **本文档结构遵循「五段式」**：当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录。
