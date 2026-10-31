"""P0 路径越界修复的回归用例（2026-10-31 全面审计 · 第三批）。

全部用例都**经 HTTP 真实调用**，修复前必须失败、修复后必须通过：

- ``T-AUD2-W0-02`` 记忆端点任意文件读/写/删（``AUD-C07`` / ``AUD-C08``）
- ``T-AUD2-W0-03`` 产物下载路径穿越（``AUD-C09``）
- ``T-AUD2-W0-04`` Skill zip 导入 name 路径穿越（``AUD-C05``）
- ``T-AUD2-W0-05`` 插件名/版本越界写（``AUD-C06``）
- ``T-AUD2-W0-06`` Skill 资源路径前缀绕过（``AUD-H18``）
- ``T-AUD2-W0-07`` 黑板跨板操作（``AUD-H17``）
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest


@pytest.fixture()
def http_client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# T-AUD2-W0-02 · 记忆端点：任意文件读 / 写 / 删
# --------------------------------------------------------------------------- #
def test_记忆端点不能删除任意文件(http_client, tmp_path):
    """``DELETE /memories`` 的 path 必须落在该作用域的记忆根内。

    **AUD-C07（critical）**：``delete_memory`` 此前是裸 ``Path(path).unlink()``，
    **零边界校验** → 默认部署（``AGENT_API_KEY`` 未配置 = **无鉴权**）下
    ``{"scope":"project","path":"/etc/passwd"}`` 可**删除任意文件**。
    """
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM", encoding="utf-8")

    resp = http_client.request(
        "DELETE", "/api/v1/memories",
        json={"scope": "project", "path": str(victim)},
    )
    assert resp.status_code == 422, resp.text
    assert victim.exists(), "受害文件被删除了！"
    assert victim.read_text(encoding="utf-8") == "VICTIM"


def test_记忆端点不能删除相对穿越路径(http_client):
    """``../../`` 形式的相对穿越同样必须被拒。"""
    resp = http_client.request(
        "DELETE", "/api/v1/memories",
        json={"scope": "project", "path": "../../../../etc/passwd"},
    )
    assert resp.status_code == 422, resp.text


def test_记忆端点不能写到工作区外(http_client, tmp_path):
    """``POST /memories`` 的 name 不得含路径分隔符。"""
    outside = tmp_path / "pwned.md"
    resp = http_client.request(
        "POST", "/api/v1/memories",
        json={"scope": "project", "name": f"../../../../{outside}", "content": "x"},
    )
    assert resp.status_code == 422, resp.text
    assert not outside.exists()
    assert not Path("/tmp/pwned.md").exists()


def test_记忆端点校验scope(http_client):
    """未知 scope → 422（此前是 500）。"""
    resp = http_client.request(
        "DELETE", "/api/v1/memories", json={"scope": "bogus", "path": "x"},
    )
    assert resp.status_code == 422, resp.text


def test_记忆端点正常读写(http_client):
    """合法路径的写入 + 删除仍应成功（不能把功能改坏）。"""
    create = http_client.request(
        "POST", "/api/v1/memories",
        json={"scope": "project", "name": "unit-test-mem", "content": "hello"},
    )
    assert create.status_code == 201, create.text
    path = create.json()["path"]

    delete = http_client.request(
        "DELETE", "/api/v1/memories", json={"scope": "project", "path": path},
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["ok"] is True


# --------------------------------------------------------------------------- #
# T-AUD2-W0-03 · 产物下载路径穿越
# --------------------------------------------------------------------------- #
def test_产物下载不能越界(http_client, tmp_path):
    """产物 path 为绝对路径 / ``../`` 时必须 403。

    **AUD-C09（critical）**：``get_workspace_dir() / str(target["path"])``
    → 绝对路径**胜出** → 读到 ``/etc/passwd``。
    """
    from app.db.base import db_session
    from app.db.models import ArtifactRow
    from sqlalchemy import text

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")

    run_id = "artifact-traversal-run"
    with db_session() as db:
        row = ArtifactRow(
            id=900001, run_id=run_id, workspace_id=None,
            path=str(secret), title="evil", mime="text/plain", size=10,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        rid, aid = row.run_id, row.id

    resp = http_client.get(f"/api/v1/runs/{rid}/artifacts/{aid}/download")
    assert resp.status_code in (403, 404), (
        f"产物下载越界未被拦截: {resp.status_code} {resp.text[:200]}"
    )
    assert "TOP-SECRET" not in resp.text


# --------------------------------------------------------------------------- #
# T-AUD2-W0-04 · Skill zip 导入 name 路径穿越
# --------------------------------------------------------------------------- #
def _skill_zip(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", f"---\nname: {name}\ndescription: evil\n---\n\nbody\n")
    return buf.getvalue()


def test_skill_zip_导入拒绝越界name(http_client, tmp_path):
    """front-matter 的 name 不得含路径分隔符。

    **AUD-C05（critical）**：zip **成员路径**做了 ``..`` 检查，
    但 front-matter 的 ``name`` 没有 → ``name: ../../../../tmp/evil``
    会在自定义技能目录**之外**建目录并写入 ``SKILL.md``。
    """
    resp = http_client.post(
        "/api/v1/skills/import",
        files={"file": ("evil.zip", _skill_zip("../../../../tmp/evil-skill"), "application/zip")},
    )
    assert resp.status_code in (400, 422), resp.text
    assert not Path("/tmp/evil-skill").exists(), "越界目录被创建了！"


def test_skill_zip_导入正常可用(http_client):
    """合法 name 的导入仍应成功。"""
    resp = http_client.post(
        "/api/v1/skills/import?overwrite=true",
        files={"file": ("ok.zip", _skill_zip("unit-import-skill"), "application/zip")},
    )
    assert resp.status_code in (200, 201), resp.text


# --------------------------------------------------------------------------- #
# T-AUD2-W0-05 · 插件名 / 版本越界写
# --------------------------------------------------------------------------- #
def test_插件安装拒绝越界名(http_client, tmp_path):
    """``plugin.json`` 的 name/version 必须是安全标识符。

    **AUD-C06（critical）**：此前**重读原始 JSON** 绕过了 ``read_manifest`` 的校验，
    ``plugin_name="../../../../tmp/evil"`` → ``copytree`` 写到插件目录**之外**。
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "plugin.json").write_text(json.dumps({
        "name": "../../../../tmp/evil-plugin",
        "version": "1.0.0",
        "skills": [],
    }), encoding="utf-8")
    (pkg / "SKILL.md").write_text(
        "---\nname: evil\ndescription: d\n---\n\nb\n", encoding="utf-8")

    resp = http_client.post(
        "/api/v1/plugins/install",
        json={"path": str(pkg)},
    )
    # 该端点的既有契约是「**200 + ok:false**」（扫描拒绝等失败路径同形态），
    # 因此按 ``ok`` 判定，而不是状态码。
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("ok") is False, f"越界插件名未被拒绝: {body}"
    assert "非法" in str(body.get("message", "")), body
    assert not Path("/tmp/evil-plugin").exists(), "越界目录被创建了！"


# --------------------------------------------------------------------------- #
# T-AUD2-W0-06 · Skill 资源路径前缀绕过
# --------------------------------------------------------------------------- #
def test_skill_资源读取不能越界(http_client, tmp_path):
    """``resource_path`` 不得借 ``startswith`` 前缀匹配逃到同级目录。

    **AUD-H18**：base=``<root>/skills/foo``、resource=``../foo_evil/x.md``
    → target=``<root>/skills/foo_evil/x.md`` → ``startswith(base)`` 为真 → 放行。
    """
    resp = http_client.get("/api/v1/skills/pdf/files/../../core/config.py")
    # 无论路由是否命中，都**不得**返回被穿越目标的文件内容
    assert "DASHSCOPE" not in resp.text, "路径穿越读到了源码！"


# --------------------------------------------------------------------------- #
# T-AUD2-W0-07 · 黑板跨板操作
# --------------------------------------------------------------------------- #
def test_黑板完成项不能跨板(http_client):
    """用 B 板的 URL 完成 A 板的 item → 必须失败，且 A 板状态不变。

    **AUD-H17**：``complete_board_item`` 的 ``board_id`` 形参**完全未使用**
    → 对 A 板的 item 调用 ``/boards/B/items/{id}/complete`` 会**完成 A 板的项**。
    """
    from app.db.base import db_session
    from app.db.models import BoardItemRow
    from sqlalchemy import text

    with db_session() as db:
        db.execute(text("DELETE FROM board_items WHERE id = 900101"))
        db.add(BoardItemRow(id=900101, board_id="board-A", title="A 的项", status="pending"))
        db.flush()

    resp = http_client.post(
        "/api/v1/boards/board-B/items/900101/complete",
        json={"result": {"ok": True}},
    )
    assert resp.status_code in (404, 422, 400), resp.text

    with db_session() as db:
        status = db.execute(
            text("SELECT status FROM board_items WHERE id = 900101")
        ).fetchone()
    assert status and status[0] == "pending", f"A 板的项被跨板改成了 {status}"
