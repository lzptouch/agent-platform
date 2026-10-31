"""统一应用配置（合并 MCP / Skill / webResearch 三项目）。

- 风格：pydantic-settings（Skill 骨架）+ `@lru_cache` 单例 + `resolve()` 路径辅助（借鉴 WR）
- `.env` 位于项目根目录，环境变量自动映射到小写字段名
"""
from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> app/core -> app -> 项目根目录
APP_DIR: Path = Path(__file__).resolve().parent.parent
PROJECT_ROOT: Path = APP_DIR.parent


def _env_flag(name: str, default: bool = False) -> bool:
    """读取布尔环境变量（1/true/yes/on 视为真）。"""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "agent"
    app_version: str = "1.1.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    # ---------- 敏感信息处置（P2-07）----------
    # allow = 只记录不改内容；encrypt = 允许并加密（密文进上下文，输出还原）；deny = 命中即拒
    sensitive_policy: str = "encrypt"
    # P2-04：DR 迭代中的事实核查开关（默认开启；关闭可省一次 LLM 调用）
    research_fact_check: bool = True

    # ---------- 主 LLM（DashScope OpenAI 兼容，Agent 循环）----------
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model: str = "qwen-plus"
    max_tokens: int = 8192
    max_iterations: int = 20
    # P2-05：Skill 轻量索引渐进披露的 Top-K
    skill_match_top_k: int = 3
    # P3-03：反思轮数上限（plan→action→reflection→action 的**轮数**硬上限）
    reflection_max_rounds: int = 2
    exec_timeout: int = 180

    # ---------- 备选 LLM（OpenAI 兼容：DeepSeek 等，RAG / planner / reflection）----------
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    plan_model: str = "deepseek-chat"
    rag_model: str = "deepseek-chat"
    answer_model: str = "deepseek-reasoner"

    # ---------- OpenAI（Web Research 专用，可选）----------
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # ---------- Web 形态最小鉴权（P1-01）----------
    #: 留空 = **不启用**（单机自用默认形态，避免打断既有用户）。
    #: 非空时，Web 形态下所有 ``/api/v1/**`` 端点要求携带该 Key。
    #: 桌面形态不受此影响（由桌面会话守卫 + Host 白名单负责）。
    agent_api_key: str = ""

    # ---------- MCP 链路 ----------
    serper_api_key: str = ""
    gaode_api_key: str = ""
    mcp_servers_dir: Path = APP_DIR / "mcp" / "servers"
    mcp_max_servers: int = 5
    mcp_call_timeout: int = 60

    # ---------- RAG 链路（Embedding 走 DashScope API，无需本地模型）----------
    # 注意：不能用 MILVUS_URI 作环境变量名（pymilvus/settings.py import 时会 load_dotenv 抢占它）
    milvus_db_path: str = "data/milvus.db"
    milvus_collection: str = "hybrid_demo"

    # ---------- Research 链路（deep_research · Bocha 博查搜索）----------
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bocha.cn/v1/web-search"
    bocha_default_count: int = 10
    bocha_summary: bool = True

    # ---------- Research Manager（线程池并发 + JSON 持久化）----------
    research_output_dir: str = "data/research"
    research_max_concurrent: int = 3
    research_persist: bool = True

    # ---------- 路径 ----------
    skills_dir: Path = PROJECT_ROOT / "skills"
    data_dir: Path = PROJECT_ROOT / "data"

    # ---------- 数据库（SQLite 默认，DATABASE_URL 可切 PostgreSQL）----------
    database_url: str = ""
    db_echo: bool = False

    # ---------- 会话 / 双模式 ----------
    session_history_limit: int = 10
    session_history_max_chars: int = 8000
    chat_max_iterations: int = 5

    # ---------- 定时任务 ----------
    scheduler_enabled: bool = True
    tz: str = "Asia/Shanghai"
    schedule_run_timeout: int = 600
    schedule_max_concurrent: int = 2
    # P3-01：交互与调度**分开预算**——此前共用 2 个槽，
    # 一个长任务即可让所有交互请求返回 busy。
    interactive_max_concurrent: int = 4
    # P3-01：交互请求等待槽位的上限（秒）；超时才回 busy。
    interactive_queue_timeout: float = 30.0
    schedule_lease_ttl: int = 60
    schedule_lease_renew: int = 20
    schedule_daily_run_limit: int = 100
    schedule_task_soft_limit: int = 200
    schedule_stale_sweep_minutes: int = 5      # 周期巡检间隔（0 = 关闭）
    schedule_stale_sweep_grace: int = 900      # 超期判定宽限（秒），需 > schedule_run_timeout

    # ---------- 上下文经济性（S5） ----------
    context_lazy_tool_loading: bool = True   # 工具延迟装载（首轮只给目录+核心 Schema）
    context_budget_ratio: float = 0.85        # 上下文占用上限（占模型窗口比例）
    context_compact_threshold: float = 0.70   # 触发轻量压缩
    context_summary_threshold: float = 0.85   # 触发强摘要
    context_keep_recent_turns: int = 3        # 压缩后保留的最近轮数（原文）
    context_memory_enabled: bool = True       # 记忆预筛与注入
    context_memory_max: int = 5               # 单次注入记忆条数上限
    pricing_json: str = ""                    # 单价表覆盖（JSON）

    # ---------- 权限引擎（S2） ----------
    permission_approval_timeout: int = 120  # ask 审批等待上限（秒），超时按 deny
    permission_audit_enabled: bool = True   # JSONL 审计开关

    # ---------- 日志（批次 03 / WP-3.2）----------
    log_to_file: bool = True               # 是否落盘（关闭即退回纯 stderr）
    log_file_name: str = "app.log"
    log_file_max_bytes: int = 10 * 1024 * 1024   # 单文件上限（10MB）
    log_file_backup_count: int = 5               # 保留的历史文件数
    log_file_level: str = "DEBUG"                # 落盘级别阈值
    log_debug_sample_rate: float = 0.2           # DEBUG 级采样率（错误及以上全量）

    # ---------- 执行边界（批次 01 / WP-1） ----------
    # 回滚开关：置 false 即整体退回「只有命令黑名单 + 超时」的旧行为
    exec_resource_limits: bool = True
    exec_cpu_seconds: int = 60              # 子进程 CPU 时间上限（POSIX 生效）
    exec_memory_bytes: int = 1024 * 1024 * 1024  # 子进程地址空间上限（POSIX 生效）
    exec_open_files: int = 256              # 文件句柄上限（POSIX 生效）
    exec_file_size_bytes: int = 64 * 1024 * 1024  # 子进程单文件写入上限（POSIX 生效）
    exec_max_output_bytes: int = 64 * 1024  # stdout / stderr 各自上限，超出即杀
    exec_workspace_escape_check: bool = True  # 启动前拦截逃出工作目录的路径
    exec_network_enabled: bool = False      # 网络出口开关（默认关）

    # ---------- 上传限制（批次 01 / WP-2） ----------
    upload_max_file_bytes: int = 50 * 1024 * 1024    # 单文件上限（50 MB）
    upload_max_request_bytes: int = 100 * 1024 * 1024  # 单请求总量上限（100 MB）
    upload_allowed_extensions: str = ""              # 逗号分隔；留空 = 用内置白名单

    # ---------- CORS ----------
    # 允许源（逗号分隔）。桌面模式由壳注入空串 = 不允许任何跨源。
    cors_origins: str = ""

    # ---------- 路径辅助（借鉴 WR resolve 模式）----------
    def resolve(self, p: str | Path) -> str:
        path = Path(p)
        return str(path if path.is_absolute() else PROJECT_ROOT / path)

    @property
    def milvus_db_abs(self) -> str:
        return self.resolve(self.milvus_db_path)

    @property
    def data_dir_abs(self) -> str:
        return self.resolve(self.data_dir)

    @property
    def database_url_abs(self) -> str:
        """SQLite 必须用绝对路径（相对路径会随 CWD 漂移）。"""
        if self.database_url.strip():
            return self.database_url
        return f"sqlite:///{(self.user_data_dir / 'app.db').as_posix()}"

    @property
    def custom_skills_dir(self) -> Path:
        return self.user_data_dir / "skills_custom"

    @property
    def output_dir(self) -> Path:
        return self.user_data_dir / "outputs"

    @property
    def upload_dir(self) -> Path:
        return self.user_data_dir / "uploads"

    @property
    def browser_data_dir(self) -> Path:
        return self.user_data_dir / "browser_data"

    @property
    def pdf_dir(self) -> Path:
        return self.user_data_dir / "pdf"

    @property
    def logs_dir(self) -> Path:
        return self.user_data_dir / "logs"

    @property
    def research_output_abs(self) -> str:
        """``data/research`` 的绝对路径。"""
        return self.resolve(self.research_output_dir)

    # ---------- 桌面端路径 ----------
    @property
    def user_data_dir(self) -> Path:
        """可写数据根。

        开发态（未注入 ``AGENT_DATA_DIR``）等于 ``data_dir``，行为与改造前完全一致；
        桌面态由壳注入 UserData 路径，使程序目录保持只读。
        """
        override = os.environ.get("AGENT_DATA_DIR", "").strip()
        if override:
            return Path(override)
        return self.data_dir

    @property
    def runtime_root(self) -> Path:
        """程序资源根（只读）。桌面态指向打包后的 runtime/agent。"""
        override = os.environ.get("AGENT_RUNTIME_ROOT", "").strip()
        if override:
            return Path(override)
        return PROJECT_ROOT

    @property
    def builtin_skills_dir(self) -> Path:
        """内置 Skill 目录（只读）。"""
        override = os.environ.get("AGENT_SKILLS_DIR", "").strip()
        if override:
            return Path(override)
        return self.skills_dir

    @property
    def frontend_dist_dir(self) -> Path:
        """前端构建产物目录（桌面态由壳通过 AGENT_FRONTEND_DIST 注入）。"""
        override = os.environ.get("AGENT_FRONTEND_DIST", "").strip()
        if override:
            return Path(override)
        return PROJECT_ROOT.parent / "frontend" / "dist"

    @property
    def default_workspace_dir(self) -> Path:
        """默认工作区（Agent 执行 cwd / 产物目录）。"""
        override = os.environ.get("AGENT_WORKSPACE_DIR", "").strip()
        if override:
            return Path(override)
        return self.user_data_dir / "workspace"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS 允许源列表。

        - **桌面态**：不需要跨源（窗口与页面同源），固定为空；
        - **Web 形态**：必须显式配置 ``CORS_ORIGINS``。未配置时返回空列表
          （**不再回落到 ``["*"]``**）——S1 暴露面收紧，未显式授权的跨源请求一律拒绝。
        """
        if self.desktop_mode:
            return []
        raw = (self.cors_origins or "").strip()
        if not raw:
            return []
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def desktop_mode(self) -> bool:
        """桌面模式。开启后启用会话令牌校验、Host 白名单与 CORS 收窄。"""
        return _env_flag("AGENT_DESKTOP")

    @property
    def desktop_token(self) -> str:
        """常驻会话令牌（只经 X-Agent-Desktop-Token header，永不进 URL）。"""
        return os.environ.get("AGENT_DESKTOP_TOKEN", "").strip()

    @property
    def desktop_bootstrap_nonce(self) -> str:
        """一次性引导 nonce（仅用于 /__desktop/bootstrap?t=）。"""
        return os.environ.get("AGENT_DESKTOP_BOOTSTRAP_NONCE", "").strip()

    @property
    def desktop_protocol(self) -> int:
        """壳与后端的握手协议版本。"""
        try:
            return int(os.environ.get("AGENT_DESKTOP_PROTOCOL", "1"))
        except ValueError:
            return 1

    @property
    def desktop_missed_window_hours(self) -> int:
        """补跑窗口（小时）。超过该时长的错过任务只提示不补跑。"""
        try:
            return int(os.environ.get("AGENT_DESKTOP_MISSED_WINDOW_HOURS", "6"))
        except ValueError:
            return 6

    # ---------- 能力检查 ----------
    @property
    def has_api_key(self) -> bool:
        return bool(self.dashscope_api_key.strip())

    @property
    def web_search_available(self) -> bool:
        return bool(self.serper_api_key.strip())

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def bocha_configured(self) -> bool:
        return bool(self.bocha_api_key.strip())

    @property
    def research_configured(self) -> bool:
        """Research 链路是否具备检索能力（Bocha 或 Serper 任一可用）。"""
        return self.bocha_configured or self.web_search_available

    def ensure_dirs(self) -> None:
        for path in (
            self.builtin_skills_dir,
            self.user_data_dir,
            self.custom_skills_dir,
            self.output_dir,
            self.upload_dir,
            self.browser_data_dir,
            self.pdf_dir,
            self.logs_dir,
            self.default_workspace_dir,
            Path(self.research_output_abs),
        ):
            path.mkdir(parents=True, exist_ok=True)


# 可供前端切换的模型列表（DashScope OpenAI 兼容模式，均为真实可用模型）
AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "qwen-plus", "name": "Qwen-Plus", "provider": "阿里"},
    {"id": "qwen-turbo", "name": "Qwen-Turbo", "provider": "阿里"},
    {"id": "qwen-max", "name": "Qwen-Max", "provider": "阿里"},
    {"id": "qwen-long", "name": "Qwen-Long", "provider": "阿里"},
]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
