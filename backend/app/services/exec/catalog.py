"""工具目录与延迟装载（S5 / WP-5.1）。

现状：每次请求都把**全部工具的完整 Schema** 塞进上下文（体积大）。
本模块把工具拆成两份：

- **目录**（常驻）：``name`` + 一句话描述 + 命名空间 —— 体积远小于 Schema；
- **完整 Schema**：按需装载（``tool_load``）。

关键设计（诚实说明）：**Schema 列表只是给模型的提示**，不是能力闸门 ——
模型即使没装载 Schema 直接发起工具调用，执行层仍按名称执行（避免功能回归）。
延迟装载带来的收益是上下文体积，而不是"禁止调用"。

降级：``context_lazy_tool_loading=false`` → 退回全量注入。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 常驻的核心工具（Schema 直接注入，保证基本能力随时可用）
#: 默认注入的工具集。
#:
#: **必须包含两个引导工具**（``tool_search`` / ``tool_load``）——
#: 否则模型**无法调用引导工具**去装载其他工具（非核心工具全部不可达），
#: 而 prompt 又要求「先 tool_search 再 tool_load」→ 提示与工具集自相矛盾。
CORE_TOOLS = (
    "read_file", "list_directory", "write_file",
    "tool_search", "tool_load",
)

#: 工具搜索 / 装载工具本身的定义
TOOL_SEARCH_DEF: dict = {
    "name": "tool_search",
    "description": "按关键词检索可用工具目录，返回候选工具名与一句话描述。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词（名称或描述）"},
            "top_k": {"type": "integer", "description": "返回候选数量（默认 5）"},
        },
        "required": ["query"],
    },
}

TOOL_LOAD_DEF: dict = {
    "name": "tool_load",
    "description": "装载指定工具的完整调用 Schema（本轮内生效）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要装载的工具名列表",
            },
        },
        "required": ["names"],
    },
}


@dataclass(frozen=True)
class CatalogEntry:
    """目录条目（不含 Schema）。"""

    name: str
    description: str
    namespace: str

    def as_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "namespace": self.namespace}


def _namespace_of(name: str) -> str:
    if name.startswith("mcp_"):
        return "mcp"
    if name.startswith("rag_"):
        return "rag"
    if name.startswith("web_"):
        return "web"
    return "builtin"


def _first_line(desc: str) -> str:
    text = (desc or "").strip()
    return text.split("\n")[0] if text else ""


def build_catalog(tools: list[dict]) -> list[CatalogEntry]:
    """从完整工具定义生成目录（name + 一句话描述 + 命名空间）。"""
    catalog: list[CatalogEntry] = []
    for t in tools:
        name = str(t.get("name", ""))
        if not name:
            continue
        catalog.append(CatalogEntry(
            name=name,
            description=_first_line(str(t.get("description", ""))),
            namespace=_namespace_of(name),
        ))
    return catalog


def catalog_text(catalog: list[CatalogEntry]) -> str:
    """把目录渲染成一段短文本（供提示词或 UI 展示）。"""
    return "\n".join(f"- {e.name}（{e.namespace}）：{e.description}" for e in catalog)


def search_catalog(catalog: list[CatalogEntry], query: str, top_k: int = 5) -> list[CatalogEntry]:
    """按名称/描述/命名空间检索，返回 Top-K 候选（打分：名称命中 > 描述命中）。"""
    q = (query or "").strip().lower()
    if not q:
        return catalog[:top_k]
    scored: list[tuple[int, int, CatalogEntry]] = []
    for idx, e in enumerate(catalog):
        name = e.name.lower()
        desc = e.description.lower()
        hay = f"{name} {desc} {e.namespace.lower()}"
        score = 0
        if q == name:
            score = 100
        elif q in name:
            score = 60
        elif q in desc:
            score = 30
        elif all(tok and (tok in name or tok in desc) for tok in q.split()):
            score = 20
        if not score:
            # 中文等无空格查询：按**字符覆盖率**打分（子串匹配对中文无效）
            cjk_chars = [c for c in q if "\u4e00" <= c <= "\u9fff"]
            if cjk_chars:
                hits = sum(1 for c in cjk_chars if c in hay)
                if hits:
                    score = max(1, int(20 * hits / len(cjk_chars)))
        if score:
            scored.append((-score, idx, e))
    scored.sort()
    return [e for _, _, e in scored[:top_k]]


class ToolLoader:
    """本轮内的工具 Schema 装载器（幂等）。"""

    def __init__(self, all_tools: list[dict]) -> None:
        self._by_name = {str(t.get("name")): t for t in all_tools}
        self._loaded: set[str] = set()

    @property
    def loaded(self) -> set[str]:
        return set(self._loaded)

    @property
    def all_tools(self) -> list[dict]:
        """当前可装载的全部工具（供 ``tool_load`` 回查 Schema）。"""
        return list(self._by_name.values())

    def refresh(self, all_tools: list[dict]) -> None:
        """同步工具集变化（保留已装载标记）。

        **P2-02**：工具集可能随 ``enable_mcp`` / ``enable_rag`` 等开关变化，
        需要在每轮开始时同步映射，但**不能丢掉已装载状态**——否则
        「第二轮起工具集不再变化」的问题会重现。
        """
        self._by_name = {str(t.get("name")): t for t in all_tools}

    def load(self, names: list[str]) -> list[dict]:
        """装载指定工具的 Schema（重复装载幂等）。"""
        out: list[dict] = []
        for name in names:
            if name in self._loaded:
                continue
            tool = self._by_name.get(name)
            if tool is None:
                continue
            self._loaded.add(name)
            out.append(tool)
        return out

    def schema_list(self, core: tuple[str, ...] = CORE_TOOLS) -> list[dict]:
        """当前应注入的 Schema 列表（核心工具 + 本轮已装载的）。"""
        out: list[dict] = []
        for name in core:
            tool = self._by_name.get(name)
            if tool is not None:
                out.append(tool)
        for name in sorted(self._loaded):
            if name in core:
                continue
            tool = self._by_name.get(name)
            if tool is not None:
                out.append(tool)
        return out


def split_core_and_catalog(
    tools: list[dict],
    *,
    lazy: bool = True,
    core: tuple[str, ...] = CORE_TOOLS,
) -> tuple[list[dict], list[CatalogEntry]]:
    """返回 ``(注入的 Schema 列表, 目录)``。

    ``lazy=False`` → 全量注入（降级模式，与改造前行为一致）。
    """
    catalog = build_catalog(tools)
    if not lazy:
        return list(tools), catalog
    loader = ToolLoader(tools)
    return loader.schema_list(core), catalog
