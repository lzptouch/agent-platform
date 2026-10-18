"""LocalCodeExecutor —— 本地代码执行器。

对标 Anthropic 的云端代码执行沙箱：通过 ``subprocess`` 在本地执行 Python / Bash，
并把工作目录固定到 ``data/outputs``，让模型生成的文件集中落盘。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.config import settings


class LocalCodeExecutor:
    """本地代码执行器（带超时与简单危险命令拦截）。"""

    BLOCKED_COMMANDS = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"]

    # matplotlib 预处理：强制 Agg 后端（防止 plt.show() 阻塞）+ 中文字体
    MPL_PREAMBLE = (
        "import matplotlib as _mpl\n"
        "_mpl.use('Agg')\n"
        "_mpl.rcParams['font.sans-serif'] = "
        "['PingFang HK', 'Heiti TC', 'Arial Unicode MS', 'STHeiti', 'SimSong']\n"
        "_mpl.rcParams['axes.unicode_minus'] = False\n"
    )

    # reportlab 预处理：注册中文字体（缺字体时静默跳过）
    REPORTLAB_PREAMBLE = (
        "from reportlab.pdfbase import pdfmetrics as _pm\n"
        "from reportlab.pdfbase.ttfonts import TTFont as _TTFont\n"
        "for _name, _path in [('ChineseFont', '/Library/Fonts/Arial Unicode.ttf'),\n"
        "                     ('ChineseFontBold', '/System/Library/Fonts/STHeiti Medium.ttc')]:\n"
        "    try:\n"
        "        _pm.registerFont(_TTFont(_name, _path))\n"
        "    except Exception:\n"
        "        pass\n"
    )

    def __init__(self, output_dir: Path | None = None, timeout: int | None = None) -> None:
        self.output_dir = Path(output_dir or settings.output_dir)
        self.timeout = timeout or settings.exec_timeout
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 安全检查
    # ------------------------------------------------------------------ #
    def _blocked(self, text: str) -> str | None:
        for blocked in self.BLOCKED_COMMANDS:
            if blocked in text:
                return f"安全限制：禁止执行包含 '{blocked}' 的内容"
        return None

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def execute_python(self, code: str) -> dict:
        """执行 Python 代码，返回 stdout / stderr / return_code。"""
        blocked = self._blocked(code)
        if blocked:
            return {"stdout": "", "stderr": blocked, "return_code": 1}

        if "matplotlib" in code or "plt" in code:
            code = self.MPL_PREAMBLE + code
            code = code.replace("plt.show()", "# plt.show() removed - non-interactive")

        if "reportlab" in code:
            code = self.REPORTLAB_PREAMBLE + code

        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.output_dir),
            )
            return {
                "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"执行超时（{self.timeout}秒）", "return_code": 1}
        except Exception as exc:  # pragma: no cover - 兜底
            return {"stdout": "", "stderr": str(exc), "return_code": 1}

    def execute_bash(self, command: str) -> dict:
        """执行 Bash 命令，工作目录为 output_dir。"""
        blocked = self._blocked(command)
        if blocked:
            return {"stdout": "", "stderr": blocked, "return_code": 1}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.output_dir),
            )
            return {
                "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"执行超时（{self.timeout}秒）", "return_code": 1}
        except Exception as exc:  # pragma: no cover - 兜底
            return {"stdout": "", "stderr": str(exc), "return_code": 1}

    # ------------------------------------------------------------------ #
    # 文件操作
    # ------------------------------------------------------------------ #
    def read_file(self, file_path: str) -> dict:
        try:
            path = Path(file_path).expanduser()
            if not path.is_absolute():
                path = self.output_dir / path
            if not path.exists():
                return {"content": "", "error": f"文件不存在: {file_path}"}
            content = path.read_text(encoding="utf-8")
            if len(content) > 20000:
                content = content[:20000] + "\n\n... [文件过大，已截断] ..."
            return {"content": content, "error": ""}
        except Exception as exc:
            return {"content": "", "error": str(exc)}

    def write_file(self, file_path: str, content: str) -> dict:
        try:
            path = Path(file_path).expanduser()
            if not path.is_absolute():
                path = self.output_dir / path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(path), "error": ""}
        except Exception as exc:
            return {"success": False, "path": file_path, "error": str(exc)}

    def list_directory(self, dir_path: str) -> dict:
        try:
            path = Path(dir_path).expanduser()
            if not path.is_absolute():
                path = self.output_dir / path
            if not path.exists():
                return {"entries": [], "error": f"目录不存在: {dir_path}"}
            entries = [
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
                for item in sorted(path.iterdir())
            ]
            return {"entries": entries, "error": ""}
        except Exception as exc:
            return {"entries": [], "error": str(exc)}
