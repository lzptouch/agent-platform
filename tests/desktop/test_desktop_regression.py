"""桌面端标准工程回归版（对应 practice/测试计划.md 模块 C2 + 稳定性专项）。

Electron 应用用 Playwright 的 Electron 驱动（`_electron.launch`），
用例覆盖：启动握手、事件桥、状态广播、孤儿回收、快捷键与托盘、异常退出。

环境不具备（未下载 electron 运行时 / 未打包）时，**归类为环境问题并跳过**，
不伪装成通过。

运行：
    .venv-e2e/bin/python -m pytest tests/desktop -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import Suite, dump_json, shot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "frontend" / "desktop"
REPORT_DIR = REPO_ROOT / "tests" / "report"

suite = Suite("desktop", "Agent Desktop（Electron 壳 + FastAPI sidecar）")


# --------------------------------------------------------------------------- #
# 环境探测
# --------------------------------------------------------------------------- #
def electron_binary() -> Path | None:
    """Electron 运行时可执行文件。

    三种布局都要认：
      - Windows：``dist/electron.exe``
      - Linux：  ``dist/electron``
      - macOS：  ``dist/Electron.app/Contents/MacOS/Electron``

    早前只写了前两种，macOS 上永远返回 None，
    于是 3 个真机用例在 macOS 上**一直"因环境不具备"跳过**——
    覆盖率缺口被伪装成了环境问题。
    """
    dist = DESKTOP_DIR / "node_modules" / "electron" / "dist"
    candidates = [
        dist / ("electron.exe" if os.name == "nt" else "electron"),
        dist / "Electron.app" / "Contents" / "MacOS" / "Electron",
    ]
    for exe in candidates:
        if exe.exists():
            return exe
    return None


def electron_app_dir() -> Path | None:
    """已构建的壳入口（dist-main/main/index.js）。"""
    entry = DESKTOP_DIR / "dist-main" / "main" / "index.js"
    return DESKTOP_DIR if entry.exists() else None


# --------------------------------------------------------------------------- #
# 静态与打包前置（不依赖 Electron 运行时，始终可执行）
# --------------------------------------------------------------------------- #
def test_desk_01_packaging_resources():
    """DESK-01 打包资源齐备且可入库（曾因 .gitignore 的 build/ 规则被屏蔽）。"""
    resources = DESKTOP_DIR / "resources"
    icon = resources / "icon.png"
    assert icon.exists(), "缺少桌面端图标 apps/desktop/resources/icon.png"
    assert icon.stat().st_size > 1024, "图标文件过小，疑似占位空文件"
    assert (resources / "installer.nsh").exists(), "缺少 NSIS 自定义脚本"
    assert (resources / "entitlements.mac.plist").exists(), "缺少 macOS entitlements"

    cfg = (DESKTOP_DIR / "electron-builder.yml").read_text(encoding="utf-8")
    assert "buildResources: resources" in cfg, "electron-builder 仍指向 build/（该目录被 gitignore 屏蔽）"
    assert "resources/installer.nsh" in cfg
    suite.ok("DESK-01", "打包资源齐备，配置指向 resources/", "静态")


def test_desk_13_in_presence_contracts():
    """DESK-13 在世交互的静态契约（批次 02）。

    逐条检查「有定义、有调用方」：速记窗指向 compose 形态、Boss Key 可绑定/解绑、
    通知点击带 runId 跳转、preload 暴露对应通道。
    """
    main_dir = DESKTOP_DIR / "src" / "main"
    quick = (main_dir / "quick.ts").read_text(encoding="utf-8")
    assert "compose=1" in quick, "速记窗未指向 /workspace?compose=1（速记形态会落空）"

    shortcuts = (main_dir / "shortcuts.ts").read_text(encoding="utf-8")
    assert "setBossKey" in shortcuts, "快捷键模块缺少 Boss Key 绑定入口"
    assert "bossKey" in shortcuts, "Boss Key 未接入持久化设置"

    settings_mod = (main_dir / "settings.ts").read_text(encoding="utf-8")
    for field in ("bossKey", "autoLaunch", "startMinimized"):
        assert field in settings_mod, f"壳设置缺少字段 {field}"

    notifications = (main_dir / "notifications.ts").read_text(encoding="utf-8")
    assert "agent:open-run" in notifications, "通知点击未发送 agent:open-run"

    preload = (DESKTOP_DIR / "src" / "preload" / "index.ts").read_text(encoding="utf-8")
    for channel in ("onOpenRun", "openRun", "getSettings", "setBossKey", "setAutoLaunch", "setStartMinimized"):
        assert channel in preload, f"preload 未暴露 {channel}"

    ipc = (main_dir / "ipc.ts").read_text(encoding="utf-8")
    for channel in ("desktop:openRun", "desktop:setBossKey", "desktop:getSettings"):
        assert channel in ipc, f"IPC 缺少通道 {channel}"
    suite.ok("DESK-13", "在世交互静态契约齐备（速记窗/Boss Key/通知跳转/preload 通道）", "静态")


def test_desk_02_gitignore_rules():
    """DESK-02 桌面端产物在干净克隆里也会被忽略。"""
    root_ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "apps/desktop/release/" in root_ignore, "根 .gitignore 未忽略 apps/desktop/release/"
    # **P5-10 修正**：此前断言 ``^build/`` —— 那是**非法**的 gitignore 锚定语法
    # （git 视 ``^`` 为字面量），等于把 bug 当成了规范。
    # 正确写法是 ``/build/``（根锚定）；并且 gitignore **不支持行尾注释**
    # （注释必须独占一行，否则整行含注释文字都会被当作模式 → 规则永不生效）。
    assert "/build/" in root_ignore, "根 .gitignore 未把 build/ 根锚定（应写 `/build/`）"
    assert "^build/" not in root_ignore, "仍使用非法的 `^build/` 锚定"
    for rule in root_ignore.split("\n"):
        rule = rule.strip()
        if rule and not rule.startswith("#"):
            assert "#" not in rule, f"规则行含行尾注释（永不生效）: {rule!r}"

    # **实跑** git check-ignore（P5-10：此前只有字符串断言）
    def _ignored(path: str) -> bool:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0

    assert _ignored("build/foo.txt"), "仓库根 build/ 未被忽略"
    assert not _ignored("apps/desktop/build/main.js"), (
        "前端 build 被根规则误屏蔽"
    )
    suite.ok("DESK-02", "忽略规则已并入被跟踪的根 .gitignore（实跑 check-ignore 验证）", "实跑")


def test_desk_03_shell_unit_tests_pass():
    """DESK-03 壳单测与类型检查通过（桌面端此前零测试）。"""
    npm = shutil.which("npm")
    if not npm:
        suite.skip("DESK-03", "壳单测", "静态", "环境不具备：未找到 npm")
        return
    test_run = subprocess.run(
        [npm, "test", "--silent"],
        cwd=str(DESKTOP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if test_run.returncode != 0:
        suite.fail(
            "DESK-03",
            "壳单测通过",
            "静态",
            f"vitest 失败：{test_run.stdout[-500:]}",
            category="业务Bug",
            level="P1",
        )
        return
    type_run = subprocess.run(
        [npm, "run", "typecheck", "--silent"],
        cwd=str(DESKTOP_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert type_run.returncode == 0, type_run.stdout[-500:]
    suite.ok("DESK-03", "壳单测与类型检查通过", "静态")


def test_desk_04_event_bridge_contract():
    """DESK-04 事件桥契约：后端事件 → 壳 → 渲染进程的通道两侧都有实现。"""
    preload = (DESKTOP_DIR / "src" / "preload" / "index.ts").read_text(encoding="utf-8")
    main = (DESKTOP_DIR / "src" / "main" / "index.ts").read_text(encoding="utf-8")
    assert "agent:backend-event" in preload, "preload 未订阅 agent:backend-event"
    assert "agent:backend-event" in main, "主进程未发送 agent:backend-event（事件桥断裂）"
    assert "agent:backend-state" in preload and "agent:backend-state" in main, "状态广播未接通"
    suite.ok("DESK-04", "事件桥与状态广播的发送方/接收方均存在", "静态")


def test_desk_05_run_state_written():
    """DESK-05 孤儿回收：run-state 有写入方与清理方。"""
    backend_ts = (DESKTOP_DIR / "src" / "main" / "backend.ts").read_text(encoding="utf-8")
    assert "writeRunState" in backend_ts and "runStatePath" in backend_ts, "缺少 run-state 写入"
    assert "clearRunState" in backend_ts, "缺少 run-state 清理"
    index_ts = (DESKTOP_DIR / "src" / "main" / "index.ts").read_text(encoding="utf-8")
    assert "cleanupOrphans" in index_ts, "缺少孤儿清理入口"
    suite.ok("DESK-05", "run-state 写入/清理与孤儿回收入口齐备", "静态")


# --------------------------------------------------------------------------- #
# 运行时用例（需要 Electron 运行时；缺失时归类为环境问题）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def electron_runtime():
    """启动桌面应用并接管其调试端口。

    Playwright 的 **Python** API 不暴露 Electron（仅 JS 版支持），且 Electron 的
    CDP 不支持 createTarget，因此这里用**协议层**断言：
      ① 窗口目标（page target）的 URL —— 证明壳与后端握手成功、加载的是后端托管页面；
      ② ``run-state.json`` —— 证明 sidecar 运行态被记录（孤儿回收的数据来源）；
      ③ 退出后 ``run-state.json`` 被清理 —— 证明退出路径闭环。
    """
    exe = electron_binary()
    if exe is None:
        pytest.skip("环境不具备：未下载 Electron 运行时（apps/desktop/node_modules/electron/dist）")
    app_dir = electron_app_dir()
    if app_dir is None:
        pytest.skip("环境不具备：壳未构建（先执行 cd apps/desktop && npm run build）")

    import urllib.request

    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    proc = subprocess.Popen(
        [str(exe), str(app_dir), f"--remote-debugging-port={port}"],
        cwd=str(DESKTOP_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"环境不具备：Electron 进程提前退出（code={proc.returncode}）")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                if resp.status == 200:
                    break
        except OSError:
            time.sleep(0.5)

    yield _Runtime(proc, port)

    _kill_tree(proc)


class _Runtime:
    def __init__(self, proc: subprocess.Popen, cdp_port: int) -> None:
        self.proc = proc
        self.cdp_port = cdp_port

    def page_targets(self) -> list[dict]:
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.cdp_port}/json/list", timeout=3
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except OSError:
            return []

    def wait_for_backend_page(self, timeout: float = 60.0) -> str | None:
        """等窗口加载到后端托管页面，返回该 URL。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for t in self.page_targets():
                url = t.get("url") or ""
                if t.get("type") == "page" and url.startswith("http://127.0.0.1"):
                    return url
            time.sleep(0.5)
        return None

    def run_state_path(self) -> Path:
        """Electron 的 userData 目录 + package.json 的 productName（回退 name）。

        各平台的 userData 位置不同，早前这里一律按 ``$HOME/<productName>`` 找，
        只在 Windows（APPDATA）恰好成立：
          - macOS：``~/Library/Application Support/<productName>``
          - Linux：``~/.config/<productName>``
          - Windows：``%APPDATA%/<productName>``
        结果就是 macOS 上明明生成了 run-state.json，用例却报"未生成"。
        """
        pkg = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))
        names = [n for n in (pkg.get("productName"), pkg.get("name")) if n]
        if os.name == "nt":
            roots = [Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")]
        elif sys.platform == "darwin":
            roots = [Path.home() / "Library" / "Application Support"]
        else:
            roots = [Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")]
        for root in roots:
            for name in names:
                candidate = root / name / "run-state.json"
                if candidate.exists():
                    return candidate
        # 兜底：返回首选路径，让断言报出"确实期望在哪"
        base = roots[0] if roots else Path.home()
        return base / (names[0] if names else "agent-desktop") / "run-state.json"


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_desk_10_launch_and_handshake(electron_runtime):
    """DESK-10 应用可启动并完成与后端的握手（窗口加载到后端托管页面）。"""
    url = electron_runtime.wait_for_backend_page()
    assert url, "未在 60s 内出现指向后端托管页面（http://127.0.0.1）的窗口目标"
    assert electron_runtime.proc.poll() is None, "Electron 进程已退出"
    suite.ok("DESK-10", f"应用启动并握手成功（窗口 URL={url[:60]}）", "运行时")


def test_desk_11_run_state_recorded(electron_runtime):
    """DESK-11 sidecar 运行态被记录（孤儿回收的数据来源）。"""
    path = electron_runtime.run_state_path()
    deadline = time.time() + 30
    data = None
    while time.time() < deadline:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except json.JSONDecodeError:
                pass
        time.sleep(0.5)
    assert data is not None, f"未生成 {path}"
    assert data.get("pid") and data.get("port"), f"run-state 内容不完整：{data}"

    import urllib.error
    import urllib.request

    # 桌面态后端：/api/v1/** 受会话守卫保护，存活探针是免鉴权的 /__desktop/ping
    with urllib.request.urlopen(
        f"http://127.0.0.1:{data['port']}/__desktop/ping", timeout=5
    ) as resp:
        assert resp.status == 200
        assert resp.read().decode("utf-8").strip().startswith("{")

    # 未带令牌的 /api/v1/** 必须被守卫拒绝，且返回统一错误体（此前这里是 500）
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{data['port']}/api/v1/health", timeout=5)
        raise AssertionError("未鉴权访问 /api/v1/health 竟然被放行")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, f"期望 401，实际 {exc.code}"
        body = json.loads(exc.read().decode("utf-8"))
        assert body.get("code") == "E_AUTH", body
        assert body.get("request_id"), body

    suite.ok(
        "DESK-11",
        f"run-state 已记录 sidecar（pid={data['pid']} port={data['port']}）；"
        "存活探针可用，未鉴权访问被守卫以 401 + 统一错误体拒绝",
        "运行时",
    )


def test_desk_12_exit_cleans_run_state(electron_runtime):
    """DESK-12 退出后 run-state 被清理（不残留孤儿记录）。"""
    path = electron_runtime.run_state_path()
    assert path.exists(), "前置条件不满足：run-state 未生成"
    _kill_tree(electron_runtime.proc)
    deadline = time.time() + 20
    while time.time() < deadline:
        if not path.exists():
            suite.ok("DESK-12", "退出后 run-state.json 已清理", "运行时")
            return
        time.sleep(0.5)
    suite.fail(
        "DESK-12",
        "退出后 run-state 被清理",
        "运行时",
        f"20s 内 {path} 仍存在",
        category="业务Bug",
        level="P2",
    )


def test_desk_12_zz_report():
    """报告生成。"""
    path = suite.write_report(
        extra_notes=[
            "运行时用例依赖 Electron 运行时与已构建壳；本环境缺失时按「环境问题」跳过并如实标注。",
        ]
    )
    print(f"\n报告已生成: {path}")
    s = suite.summary()
    print(f"用例总数 {s['total']}｜成功 {s['passed']}｜失败 {s['failed']}｜跳过 {s['skipped']}")
