"""P5-10 · gitignore 根锚定（**实跑** `git check-ignore -v`）。

此前测试只是**字符串断言**（检查 ``.gitignore`` 里有没有某行），
从未实跑 git → 宣称的「只忽略仓库根 build/」**未达成**。

**两个真实缺陷**（均由实跑发现）：

1. ``^build/`` **不是合法 gitignore 锚定语法**（git 视 ``^`` 为字面量）；
2. gitignore **不支持行尾注释** —— ``/build/   # 说明`` 整行都会被当作模式，
   规则**永不生效**（注释必须独占一行）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _check_ignore(path: str) -> str:
    """实跑 ``git check-ignore -v``；未被忽略时返回空串。"""
    proc = subprocess.run(
        ["git", "check-ignore", "-v", path],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode == 0:
        return proc.stdout.strip()
    return ""


def _rule_lines() -> list[str]:
    """``.gitignore`` 的**规则行**（去掉空行与注释行）。"""
    out = []
    for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").split("\n"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append(ln)
    return out


class TestGitignoreAnchoring:
    """根锚定的真实行为（**不是**字符串断言）。"""

    def test_仓库根build被忽略(self):
        """根 ``build/`` **确实被忽略**（实跑 git 判定）。"""
        hit = _check_ignore("build/foo.txt")
        assert hit, "仓库根 build/ 未被忽略"

    def test_前端resources不被忽略(self):
        """``frontend/desktop/resources/**`` **无命中**（曾被 ``^build/`` 误屏蔽）。"""
        hit = _check_ignore("frontend/desktop/resources/icon.png")
        assert not hit, f"前端资源被误忽略: {hit}"

    def test_桌面build不被忽略(self):
        """``frontend/desktop/build/**`` 不应被根规则命中。"""
        hit = _check_ignore("frontend/desktop/build/main.js")
        assert not hit, f"前端 build 被误忽略: {hit}"

    def test_规则用合法根锚定语法(self):
        """规则行写成 ``/build/``（``^build/`` 不是合法锚定语法）。"""
        rules = _rule_lines()
        assert "/build/" in rules, f"缺少 `/build/` 根锚定规则: {rules}"
        assert not any(r.startswith("^") for r in rules), "仍有 `^` 开头的非法锚定"

    def test_规则行不带行尾注释(self):
        """gitignore **不支持行尾注释**——带注释的规则行永远不会生效。"""
        for rule in _rule_lines():
            assert "#" not in rule, (
                f"规则行含行尾注释（整行会被当作模式，规则永不生效）: {rule!r}"
            )
