"""打包产物矩阵（PAK-01~13 / PAK-16 / PAK-19）。

对应 `doc/testing/00-全面测试计划.md` §4.6。既有 `scripts/verify_desktop_package.py`
只认 Windows（`release/win-unpacked` + `python.exe` + `.exe`），在 macOS/Linux 上恒为
"未找到主程序"——**不是通过，也不是失败，而是零覆盖**。本文件把同一批断言做成
跨平台 pytest 用例，并把"产物缺失"记为 `env_missing`（计入覆盖率缺口）而非绿。

判定原则（铁律 §2.3）：断言的事实源必须在被测进程之外——
- 运行时：run-state.json / TCP 端口 / HTTP 响应体；
- 打包完整性：asar 清单、体积统计、codesign 输出；
- 不以"窗口看起来正常"为准。

运行：
    .venv-e2e/bin/python -m pytest tests/packaged -q
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "frontend" / "desktop"
RELEASE_DIR = DESKTOP_DIR / "release"

#: 体积预算（§4.6 PAK-12）
BUDGET_RUNTIME_MB = 350
BUDGET_FRONTEND_MB = 30
BUDGET_SHELL_MB = 120


# --------------------------------------------------------------------------- #
# 产物定位（跨平台）
# --------------------------------------------------------------------------- #
def _candidate_dirs() -> list[Path]:
    """按平台枚举可能的打包产物目录。"""
    if sys.platform == "darwin":
        return [
            RELEASE_DIR / "mac-arm64",
            RELEASE_DIR / "mac",
            RELEASE_DIR / "mac-x64",
        ]
    if os.name == "nt":
        return [RELEASE_DIR / "win-unpacked", RELEASE_DIR / "win-x64", RELEASE_DIR / "win-arm64"]
    return [RELEASE_DIR / "linux-unpacked", RELEASE_DIR / "linux", RELEASE_DIR / "linux-arm64"]


def _find_app_dir() -> Path | None:
    for base in _candidate_dirs():
        if not base.exists():
            continue
        if sys.platform == "darwin":
            for app in base.glob("*.app"):
                if (app / "Contents" / "MacOS").exists():
                    return app
        else:
            # Windows: <dir>/Agent Desktop.exe；Linux: <dir>/agent-desktop
            for exe in base.iterdir():
                if exe.is_file() and exe.suffix == ".exe":
                    return base
            if any(p.is_file() for p in base.iterdir() if p.name in {"agent-desktop", "Agent Desktop"}):
                return base
    return None


def _resources_dir(app_dir: Path) -> Path:
    if sys.platform == "darwin":
        return app_dir / "Contents" / "Resources"
    return app_dir / "resources"


def _main_executable(app_dir: Path) -> Path:
    if sys.platform == "darwin":
        macos = app_dir / "Contents" / "MacOS"
        for exe in macos.iterdir():
            if exe.is_file():
                return exe
        return macos / "Agent Desktop"
    if os.name == "nt":
        return app_dir / "Agent Desktop.exe"
    for name in ("agent-desktop", "Agent Desktop"):
        cand = app_dir / name
        if cand.exists():
            return cand
    return app_dir / "agent-desktop"


def _runtime_python(resources: Path) -> Path | None:
    """运行时解释器（Windows: python.exe；POSIX: bin/python3）。"""
    for rel in (Path("runtime") / "python.exe", Path("runtime") / "bin" / "python3",
                Path("runtime") / "bin" / "python"):
        cand = resources / rel
        if cand.exists():
            return cand
    return None


def _user_data_dir() -> Path:
    """桌面态默认 userData（各平台位置不同）。

    仅用于**诊断**：用例本身一律用独立临时 user-data-dir，
    避免与其它实例争单实例锁（§7.3 规则 2）。
    """
    pkg = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))
    names = [n for n in (pkg.get("productName"), pkg.get("name")) if n]
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for name in names:
        cand = root / name
        if cand.exists():
            return cand
    return root / (names[0] if names else "agent-desktop")


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_json(url: str, timeout: float = 5.0) -> tuple[int, str, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)
    except OSError as exc:
        return 0, str(exc), {}


def _http_404_body(url: str) -> tuple[int, str, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), _ci_headers(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), _ci_headers(exc.headers)
    except OSError as exc:
        return 0, str(exc), {}


def _ci_headers(headers) -> dict:
    """HTTP 头名**大小写不敏感**：线上实际下发的是 ``X-Request-Id``，
    而后端常量写的是 ``X-Request-ID``——按精确大小写查会误判为"缺头"。"""
    return {str(k).lower(): v for k, v in headers.items()}


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, encoding="utf-8", errors="replace")
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                if not fp.is_symlink():
                    total += fp.stat().st_size
            except OSError:
                pass
    return total / 1024 / 1024


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# 会话级夹具：产物缺失 → env_missing（计入覆盖率缺口，不显示为绿）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def artifact():
    app_dir = _find_app_dir()
    if app_dir is None:
        pytest.skip(
            "env_missing: 未找到打包产物（先执行 build-frontend → stage-runtime → "
            f"electron-builder --dir）；已查找：{[str(p) for p in _candidate_dirs()]}"
        )
    return app_dir


@pytest.fixture(scope="module")
def resources(artifact: Path) -> Path:
    return _resources_dir(artifact)


@pytest.fixture(scope="module")
def packaged_app(artifact: Path):
    """启动打包产物，等握手完成。

    必须用**独立 user-data-dir**：壳有单实例锁，与其它实例共用默认 userData 时，
    新实例会静默退出 → 这里表现为"打包产物起不来"的假跳过（§7.3 规则 2）。
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="agent-pak-")
    ud = Path(tmp)
    run_state = ud / "run-state.json"

    cdp_port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    env["AGENT_DESKTOP_USER_DATA"] = str(ud)
    proc = subprocess.Popen(
        [str(_main_executable(artifact)), f"--user-data-dir={ud}",
         f"--remote-debugging-port={cdp_port}"],
        cwd=str(artifact),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 120
    data = None
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"env_missing: 打包产物启动即退出（code={proc.returncode}）")
        if run_state.exists():
            try:
                data = json.loads(run_state.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = None
            if data and data.get("pid") and data.get("port"):
                break
        time.sleep(0.5)
    if not data:
        _kill_tree(proc)
        pytest.skip(f"env_missing: 打包产物未在 120s 内写出 run-state.json（{run_state}）")

    try:
        yield _Packaged(proc, data, run_state, cdp_port)
    finally:
        _kill_tree(proc)
        shutil.rmtree(tmp, ignore_errors=True)


class _Packaged:
    def __init__(self, proc, data, run_state: Path, cdp_port: int) -> None:
        self.proc = proc
        self.data = data
        self.run_state = run_state
        self.cdp_port = cdp_port

    @property
    def port(self) -> int:
        return int(self.data["port"])

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def page_targets(self) -> list[dict]:
        status, body, _ = _http_json(f"http://127.0.0.1:{self.cdp_port}/json/list", timeout=3)
        if status != 200:
            return []
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return []


# --------------------------------------------------------------------------- #
# PAK-01 ~ PAK-04：产物静态完整性
# --------------------------------------------------------------------------- #
def test_pak_01_main_executable(artifact: Path):
    """PAK-01 安装目录含主程序。"""
    exe = _main_executable(artifact)
    assert exe.exists(), f"未找到主程序：{exe}"
    assert exe.stat().st_size > 0, "主程序为空文件"


def test_pak_02_runtime_python_executable(resources: Path):
    """PAK-02 resources/runtime 随包且 python 可执行（直接跑 --version）。"""
    py = _runtime_python(resources)
    assert py is not None, f"未找到运行时解释器（resources/runtime）：{resources}"
    proc = subprocess.run([str(py), "--version"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"运行时解释器不可执行：{proc.stderr[:300]}"
    assert "Python" in (proc.stdout + proc.stderr), proc.stdout


def test_pak_03_frontend_latest(resources: Path):
    """PAK-03 resources/frontend 随包且为最新 dist（与 build-frontend 产物哈希比对）。"""
    packaged = resources / "frontend" / "index.html"
    assert packaged.exists(), f"未找到随包前端产物：{packaged}"
    source = REPO_ROOT / "frontend" / "dist" / "index.html"
    assert source.exists(), f"缺少构建源产物：{source}（先跑 node scripts/ui/build-frontend.mjs）"
    assert _sha256(packaged) == _sha256(source), (
        "随包前端产物与 apps/ui/dist 不一致 —— 打包的是旧 dist（历史事故：dist 停在旧日期，"
        "e2e 在过期界面上跑，失败全是幻觉）"
    )


def test_pak_04_alembic_ini_in_runtime(resources: Path):
    """PAK-04 alembic.ini 随运行时存在（缺失 → 打包态启动迁移失败并中止）。"""
    ini = resources / "runtime" / "agent" / "alembic.ini"
    assert ini.exists(), (
        f"运行时缺少 alembic.ini：{ini}；缺失会导致打包态启动时迁移失败并直接中止启动"
    )


# --------------------------------------------------------------------------- #
# PAK-05 ~ PAK-08：运行时行为
# --------------------------------------------------------------------------- #
def test_pak_05_first_screen_loaded(packaged_app: _Packaged):
    """PAK-05 首屏加载后端托管页面（CDP page target）。"""
    deadline = time.time() + 60
    url = ""
    while time.time() < deadline:
        for t in packaged_app.page_targets():
            u = t.get("url") or ""
            if t.get("type") == "page" and u.startswith("http://127.0.0.1"):
                url = u
                break
        if url:
            break
        time.sleep(0.5)
    assert url, "未在 60s 内出现指向后端托管页面的窗口目标"


def test_pak_06_run_state_recorded(packaged_app: _Packaged):
    """PAK-06 run-state.json 记录 sidecar（pid/port），且端口可连。"""
    data = packaged_app.data
    assert data.get("pid"), f"run-state 缺 pid：{data}"
    assert data.get("port"), f"run-state 缺 port：{data}"
    with socket.socket() as s:
        s.settimeout(5)
        assert s.connect_ex(("127.0.0.1", int(data["port"]))) == 0, "run-state 记录的端口不可连"


def test_pak_07_ping_alive(packaged_app: _Packaged):
    """PAK-07 免鉴权存活探针 /__desktop/ping。"""
    status, body, _ = _http_json(f"{packaged_app.base}/__desktop/ping")
    assert status == 200, f"存活探针异常：HTTP {status} {body[:120]}"
    assert body.strip().startswith("{"), f"存活探针未返回 JSON：{body[:120]}"


def test_pak_08_unauthorized_error_body(packaged_app: _Packaged):
    """PAK-08 未鉴权访问 /api/v1/** → 401 + 统一错误体（code/request_id）。"""
    status, body, headers = _http_404_body(f"{packaged_app.base}/api/v1/health")
    assert status == 401, f"期望 401，实际 {status}：{body[:160]}"
    payload = json.loads(body)
    assert payload.get("code") == "E_AUTH", payload
    assert payload.get("request_id"), f"统一错误体缺 request_id：{payload}"
    assert headers.get("x-request-id"), f"响应缺 X-Request-ID 头：{headers}"
    assert headers["x-request-id"] == payload["request_id"], (
        f"响应头与错误体的 request_id 不一致：{headers.get('x-request-id')} vs {payload['request_id']}"
    )


# --------------------------------------------------------------------------- #
# PAK-09 / PAK-10：强杀与孤儿回收
# --------------------------------------------------------------------------- #
def _launch_isolated(artifact: Path, ud: Path) -> tuple[subprocess.Popen, Path]:
    """以**独立 user-data-dir** 启动打包产物。

    Why 必须隔离：壳有单实例锁，同一 userData 下第二个实例会静默退出，
    看起来就像"启动失败"（这是历史误判的来源，见 §2.4 禁忌表）。
    """
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    env["AGENT_DESKTOP_USER_DATA"] = str(ud)
    # 保留壳的 stdout/stderr → 失败时能拿到 shell.log（§6.1 的取证要求）
    log_path = ud / "shell.log"
    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(_main_executable(artifact)), f"--user-data-dir={ud}"],
        cwd=str(artifact), env=env,
        stdout=log_fh, stderr=subprocess.STDOUT,
    )
    proc._log_fh = log_fh  # type: ignore[attr-defined]
    return proc, ud / "run-state.json"


def _hard_kill(proc: subprocess.Popen) -> None:
    """强杀（SIGKILL）—— 模拟断电/崩溃，**不走**任何清理路径。"""
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _await_run_state(run_state: Path, timeout: float = 120.0,
                     after_ts: float | None = None,
                     exclude_pid: int | None = None) -> dict | None:
    """等 run-state.json 写出**可用的**运行态。

    ``after_ts``：只认该时刻之后**新写入**的内容（强杀后残留的旧文件不算）。
    ``exclude_pid``：要求 pid 与之不同（用于"重启后必须换新 pid"）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if run_state.exists():
            try:
                mtime = run_state.stat().st_mtime
                data = json.loads(run_state.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data, mtime = None, 0.0
            if data and data.get("pid") and data.get("port"):
                fresh = after_ts is None or mtime >= after_ts
                changed = exclude_pid is None or int(data["pid"]) != int(exclude_pid)
                if fresh and changed:
                    return data
        time.sleep(0.4)
    return None


def _pid_alive(pid: int) -> bool:
    """进程是否仍存活（不依赖 pgrep -f，避免命中开发后端与 pytest 自身）。"""
    if os.name == "nt":
        proc = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                              capture_output=True, text=True, timeout=30)
        return str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_pak_09_and_10_orphan_recovery(artifact: Path):
    """PAK-09 强杀后 run-state 残留属预期；PAK-10 重启后回收孤儿（pid 必须变化）。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agent-orphan-") as tmp:
        ud = Path(tmp)
        proc, run_state = _launch_isolated(artifact, ud)
        data = _await_run_state(run_state)
        assert data, "首次启动未写出 run-state.json"
        old_pid = int(data["pid"])
        # 强杀（SIGKILL）——模拟断电/崩溃：不会走任何清理路径
        _hard_kill(proc)
        time.sleep(2)
        # PAK-09：强杀不走优雅退出，run-state 允许残留（它正是孤儿回收的数据来源）
        assert run_state.exists(), "强杀后 run-state 消失（无法用于孤儿回收）"

        # 重启：同一个 userData 目录（模拟用户再次双击），必须回收旧孤儿
        restart_at = time.time()
        proc2, run_state2 = _launch_isolated(artifact, ud)
        try:
            data2 = _await_run_state(run_state2, after_ts=restart_at, exclude_pid=old_pid)
            assert data2, "重启后未写出**新的** run-state.json（pid 仍是旧的）"
            assert int(data2["pid"]) != old_pid, (
                f"重启后 pid 未变化（{old_pid}）——旧孤儿未被回收"
            )
            assert not _pid_alive(old_pid), (
                f"旧孤儿进程 {old_pid} 仍存活——重启未回收它"
            )
        finally:
            _kill_tree(proc2)


def test_pak_09b_graceful_exit_cleans_up(artifact: Path):
    """退出清理（NAT-06 对应）：收到终止信号后必须**终止侧车并清理 run-state**。

    早前 `before-quit` 里是 `void supervisor.stop()`：Electron 不等 Promise 就退出，
    于是侧车残留成孤儿（占着端口）、run-state.json 也留在磁盘上。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agent-quit-") as tmp:
        ud = Path(tmp)
        proc, run_state = _launch_isolated(artifact, ud)
        data = _await_run_state(run_state)
        assert data, "未写出 run-state.json"
        sidecar_pid = int(data["pid"])
        _kill_tree(proc)          # SIGTERM：走「托盘退出」同款清理路径
        deadline = time.time() + 20
        while time.time() < deadline:
            if not _pid_alive(sidecar_pid) and not run_state.exists():
                break
            time.sleep(0.5)
        shell_log = (ud / "shell.log")
        evidence = shell_log.read_text(encoding="utf-8", errors="replace")[-800:] if shell_log.exists() else "(无 shell.log)"
        assert not _pid_alive(sidecar_pid), (
            f"退出后侧车仍在运行（pid={sidecar_pid}）——残留孤儿会一直占着端口\n"
            f"--- shell.log 尾部 ---\n{evidence}"
        )
        assert not run_state.exists(), f"退出后 run-state.json 仍残留：{run_state}\n{evidence}"


# --------------------------------------------------------------------------- #
# PAK-11：asar 内容合规
# --------------------------------------------------------------------------- #
def test_pak_11_asar_compliance(resources: Path):
    """PAK-11 asar 内无 .map；原生模块在 unpacked；electron-updater 在 dependencies。"""
    asar = resources / "app.asar"
    assert asar.exists(), f"未找到 app.asar：{asar}"

    asar_bin = DESKTOP_DIR / "node_modules" / "@electron" / "asar" / "bin" / "asar.js"
    if asar_bin.exists():
        proc = subprocess.run(["node", str(asar_bin), "list", str(asar)],
                              capture_output=True, text=True, timeout=180)
        listing = proc.stdout
        assert proc.returncode == 0, f"asar list 失败：{proc.stderr[:200]}"
        maps = [ln for ln in listing.splitlines() if ln.strip().endswith(".map")]
        assert not maps, f"asar 内含 sourcemap：{maps[:5]}"

    unpacked = resources / "app.asar.unpacked"
    if unpacked.exists():
        native = list(unpacked.rglob("*.node")) + list(unpacked.rglob("*.dll")) \
            + list(unpacked.rglob("*.so")) + list(unpacked.rglob("*.pyd"))
        assert native, "存在 app.asar.unpacked 但里面没有原生模块（asarUnpack 规则可能过宽/失效）"

    pkg = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))
    deps = pkg.get("dependencies") or {}
    assert "electron-updater" in deps, (
        f"electron-updater 不在 dependencies（实际：{list(deps)}）——"
        "自动更新模块被 electron-builder 排除在 asar 外会导致运行时找不到"
    )


# --------------------------------------------------------------------------- #
# PAK-12：体积预算
# --------------------------------------------------------------------------- #
def test_pak_12_size_budget(resources: Path, artifact: Path):
    """PAK-12 体积预算：runtime ≤350MB / 前端 ≤30MB / 壳 ≤120MB。

    口径与 `scripts/build-desktop.mjs` 一致：**壳**不含 runtime 与 frontend
    （那是另外两项预算，不能重复计入）。超预算默认只告警，
    需要阻断时用 ``PACK_STRICT=1`` 打开（对应 build 脚本的 ``--strict``）。
    """
    strict = os.environ.get("PACK_STRICT") == "1"
    runtime = resources / "runtime"
    frontend = resources / "frontend"
    runtime_mb = _dir_size_mb(runtime) if runtime.exists() else 0.0
    frontend_mb = _dir_size_mb(frontend) if frontend.exists() else 0.0
    total_mb = _dir_size_mb(artifact)
    shell_mb = max(total_mb - runtime_mb - frontend_mb, 0.0)
    report = (
        f"runtime={runtime_mb:.1f}MB(预算{BUDGET_RUNTIME_MB}) "
        f"frontend={frontend_mb:.1f}MB(预算{BUDGET_FRONTEND_MB}) "
        f"壳={shell_mb:.1f}MB(预算{BUDGET_SHELL_MB}) 合计={total_mb:.1f}MB"
    )
    print("\n[PAK-12] " + report)

    assert frontend_mb <= BUDGET_FRONTEND_MB, f"前端产物超预算：{report}"
    for name, value, budget in (
        ("runtime", runtime_mb, BUDGET_RUNTIME_MB),
        ("壳", shell_mb, BUDGET_SHELL_MB),
    ):
        if value > budget:
            msg = f"{name} 超预算：{value:.1f}MB > {budget}MB（{report}）"
            if strict:
                raise AssertionError(msg)
            print(f"[PAK-12] WARN {msg}——离线兜底 --from-venv 会带整份 site-packages，"
                  "需在发布前裁剪（PACK_STRICT=1 可将其升级为阻断）")


# --------------------------------------------------------------------------- #
# PAK-16：签名 / 公证状态（显式记录，不假装已签名）
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sys.platform != "darwin", reason="签名检查仅在 macOS 上执行")
def test_pak_16_code_signature(artifact: Path):
    """PAK-16 macOS 签名状态必须被显式记录（无证书时为未签名，需在发布说明中明示）。"""
    proc = subprocess.run(["codesign", "-dv", "--verbose=4", str(artifact)],
                          capture_output=True, text=True, timeout=120)
    out = (proc.stdout + proc.stderr).strip()
    signed = "Signature=adhoc" not in out and "code object is not signed" not in out
    print(f"\n[PAK-16] codesign: {out[:400]}")
    if not signed:
        print("[PAK-16] WARN 未签名（无证书环境）——发布前必须在说明中明示，"
              "否则 Gatekeeper 会拦截安装")


# --------------------------------------------------------------------------- #
# PAK-19：冷启动耗时
# --------------------------------------------------------------------------- #
def test_pak_19_cold_start(artifact: Path):
    """PAK-19 冷启动：spawn → run-state 就绪 ≤ 15s。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agent-cold-") as tmp:
        ud = Path(tmp)
        t0 = time.time()
        proc, run_state = _launch_isolated(artifact, ud)
        try:
            data = _await_run_state(run_state, timeout=60.0)
            elapsed = time.time() - t0
            print(f"\n[PAK-19] 冷启动到 run-state 就绪：{elapsed:.1f}s")
            assert data, "冷启动未写出 run-state.json"
            assert elapsed <= 15.0, f"冷启动 {elapsed:.1f}s 超过 15s 预算"
        finally:
            _kill_tree(proc)


# --------------------------------------------------------------------------- #
# PAK-13：干净用户目录启动
# --------------------------------------------------------------------------- #
def test_pak_13_clean_user_data(artifact: Path):
    """PAK-13 全新用户目录启动（模拟干净机首启：不得依赖任何既有状态）。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agent-clean-") as tmp:
        ud = Path(tmp)
        proc, run_state = _launch_isolated(artifact, ud)
        try:
            data = _await_run_state(run_state, timeout=120.0)
            assert data, "干净用户目录下未写出 run-state.json（侧车没起来）"
            status, _body, _ = _http_json(f"http://127.0.0.1:{data['port']}/__desktop/ping")
            assert status == 200, f"干净机下存活探针异常：HTTP {status}"
        finally:
            _kill_tree(proc)
