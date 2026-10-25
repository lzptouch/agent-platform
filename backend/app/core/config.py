"""统一应用配置（合并 MCP / Skill / webResearch 三项目）。

- 风格：pydantic-settings（Skill 骨架）+ `@lru_cache` 单例 + `resolve()` 路径辅助（借鉴 WR）
- `.env` 位于项目根目录，环境变量自动映射到小写字段名
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> app/core -> app -> 项目根目录
APP_DIR: Path = Path(__file__).resolve().parent.parent
PROJECT_ROOT: Path = APP_DIR.parent


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
    host: str = "0.0.0.0"
    port: int = 8000

    # ---------- 主 LLM（DashScope OpenAI 兼容，Agent 循环）----------
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model: str = "qwen-plus"
    max_tokens: int = 8192
    max_iterations: int = 20
    exec_timeout: int = 180

    # ---------- 备选 LLM（OpenAI 兼容：DeepSeek 等，RAG / planner / reflection）----------
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    plan_model: str = "deepseek-chat"
    rag_model: str = "deepseek-chat"
    answer_model: str = "deepseek-reasoner"

    # ---------- OpenAI（Web Research 专用，可选）----------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

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
    save_chat_log: bool = False  # 会话入库后默认关闭旧 JSON 调试日志

    # ---------- 定时任务 ----------
    scheduler_enabled: bool = True
    tz: str = "Asia/Shanghai"
    schedule_run_timeout: int = 600
    schedule_max_concurrent: int = 2
    schedule_lease_ttl: int = 60
    schedule_lease_renew: int = 20
    schedule_daily_run_limit: int = 100
    schedule_task_soft_limit: int = 200

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
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def custom_skills_dir(self) -> Path:
        return self.data_dir / "skills_custom"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def browser_data_dir(self) -> Path:
        return self.data_dir / "browser_data"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdf"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def research_output_abs(self) -> str:
        """``data/research`` 的绝对路径。"""
        return self.resolve(self.research_output_dir)

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
            self.skills_dir,
            self.data_dir,
            self.custom_skills_dir,
            self.output_dir,
            self.upload_dir,
            self.browser_data_dir,
            self.pdf_dir,
            self.logs_dir,
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
