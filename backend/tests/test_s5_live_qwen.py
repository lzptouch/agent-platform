"""L4 真实模型测试（统一使用**千问**，S5 / WP-5.5）。

验证"计量 → 成本 → 账本"这条链路在真实调用下成立：
每次调用有计量记录、run 级 token 可加总、历史金额不随单价变更而变。

**这些用例会真实调用模型**（消耗额度），因此：
- 未配置 ``DASHSCOPE_API_KEY`` 时整体跳过；
- 默认模型取自 ``settings.default_model``（当前统一为千问）；
- 每次只发极短 prompt，控制成本。
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.pricing import DEFAULT_PRICES, calculate_cost
from app.db.base import db_session
from app.db.models import LlmCallRow, RunRow, utc_now
from app.services.exec.accounting import aggregate_run, record_call

pytestmark = pytest.mark.skipif(
    not settings.dashscope_api_key.strip(),
    reason="未配置 DASHSCOPE_API_KEY，跳过真实模型测试",
)



#: **账号状态类**错误 → 环境问题（跳过），不属于代码缺陷
_ENV_ERROR_CODES = (
    "Arrearage",          # 欠费
    "AccessDenied",       # 权限被撤销
    "InvalidApiKey",      # 密钥失效
    "Throttling",         # 限流（临时环境问题）
    "ServiceUnavailable",
)


def _skip_if_env_issue(exc: BaseException) -> None:
    """若异常属于**账号/服务状态**问题 → 跳过；否则原样抛出。"""
    text = str(exc)
    if any(code in text for code in _ENV_ERROR_CODES):
        pytest.skip(f"环境问题（账号/服务状态）：{type(exc).__name__}: {text[:160]}")
    raise exc


@pytest.fixture()
def live_run_id() -> str:
    """建一条真实的 run 行（用于挂计量）。"""
    from app.db.base import db_session as _s

    with _s() as db:
        row = RunRow(trigger="api", status="running", meta_json="{}", created_at=utc_now())
        db.add(row)
        db.flush()
        rid = row.id
    yield rid
    with db_session() as db:
        row = db.get(RunRow, rid)
        if row is not None:
            db.delete(row)


class TestLiveQwen:
    def test_千问连通性(self):
        """真实调用一次千问，确认密钥与模型可用。"""
        from app.core.llm import get_llm_client

        client = get_llm_client("dashscope")
        try:
            resp = client.chat.completions.create(
                model=settings.default_model,
                messages=[{"role": "user", "content": "只回复一个字：好"}],
                max_tokens=8,
            )
        except Exception as exc:  # noqa: BLE001 - 账号状态问题 → 环境问题
            _skip_if_env_issue(exc)
            raise
        assert resp.choices[0].message.content
        usage = getattr(resp, "usage", None)
        assert usage is not None and usage.total_tokens > 0

    def test_真实调用有计量且可加总(self, live_run_id):
        """真实调用 → 计量落库 → run 级聚合可加总。"""
        from app.core.llm import get_llm_client
        from app.services.exec.accounting import CallUsage

        client = get_llm_client("dashscope")
        try:
            resp = client.chat.completions.create(
                model=settings.default_model,
                messages=[{"role": "user", "content": "回复：测试"}],
                max_tokens=8,
            )
        except Exception as exc:  # noqa: BLE001 - 账号状态问题 → 环境问题
            _skip_if_env_issue(exc)
            raise
        usage = getattr(resp, "usage", None)
        record_call(
            CallUsage(
                model=settings.default_model,
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                latency_ms=100,
            ),
            run_id=live_run_id,
        )
        with db_session() as db:
            row = db.scalars(
                __import__("sqlalchemy").select(LlmCallRow).where(LlmCallRow.run_id == live_run_id)
            ).first()
            assert row is not None, "真实调用应有计量记录"
            assert row.prompt_tokens > 0
            assert row.cost > 0
            assert row.price_snapshot, "应保存单价快照"

        agg = aggregate_run(live_run_id)
        assert agg["llm_calls"] == 1
        assert agg["prompt_tokens"] > 0

    def test_历史金额不随单价变更而变(self, live_run_id):
        """改价后，已落库的历史调用金额不变（靠单价快照）。"""
        from app.services.exec.accounting import CallUsage

        record_call(
            CallUsage(model=settings.default_model, prompt_tokens=1000, completion_tokens=1000),
            run_id=live_run_id,
        )
        with db_session() as db:
            row = db.scalars(
                __import__("sqlalchemy").select(LlmCallRow).where(LlmCallRow.run_id == live_run_id)
            ).first()
            assert row is not None
            stored_cost = row.cost
            snapshot = row.price_snapshot

        price = DEFAULT_PRICES.get(settings.default_model)
        assert price is not None, "千问模型应在单价表内"
        expected = (price.input_per_1k + price.output_per_1k)
        assert abs(stored_cost - expected) < 1e-6

        # 改价（模拟后续调价）
        DEFAULT_PRICES[settings.default_model] = type(price)("dashscope", 99.0, 99.0)
        try:
            new_cost, _ = calculate_cost(settings.default_model, 1000, 1000)
            assert new_cost != stored_cost, "新计算应随改价变化"
            with db_session() as db:
                row2 = db.scalars(
                    __import__("sqlalchemy").select(LlmCallRow).where(LlmCallRow.run_id == live_run_id)
                ).first()
                assert row2 is not None
                assert row2.cost == stored_cost, "历史金额不应变化"
                assert row2.price_snapshot == snapshot, "历史单价快照不应变化"
        finally:
            DEFAULT_PRICES[settings.default_model] = price
