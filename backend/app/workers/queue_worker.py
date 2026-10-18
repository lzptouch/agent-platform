"""异步任务消费者（worker）—— 高并发「异步化 + 队列削峰」的消费侧实现。

> ⚠️ **当前仓库不提供本组件的运行环境**：仓库内已无 Redis 实例与 worker 部署清单
> （原 K8s 清单随 CI/CD 工程一并移除），根 `docker-compose.yml` 只编排 `backend` + `web`。
> 如需启用，必须自行提供 Redis，并把 `REDIS_URL` 指向它。
> 主应用不会 import 本模块，因此缺失运行环境不影响服务启动。

设计要点（原与 K8s 清单 agent-worker 的约定一一对应）：

1. **零新增依赖**：镜像内没有 redis-py，因此这里用**标准库实现最小 RESP 客户端**
   （长连接 + `BRPOP` 阻塞读 + `AUTH/SELECT`）。生产可以直接换成 redis-py 或
   换成 Kafka/NSQ，但对 K8s 而言「消费者进程 + 就绪探针 + 优雅退出」的契约不变。

2. **就绪与排空用文件表达**（worker 无 HTTP 端口，用不了 httpGet 探针）：
   - 启动成功 → `touch /tmp/worker.ready`（readinessProbe 依赖它）
   - 收到 SIGTERM → `touch /tmp/worker.draining`（preStop 里也会 touch）
     之后停止取新任务，把手上的任务做完再退出 —— 对应
     `terminationGracePeriodSeconds: 120`，避免任务被腰斩。

3. **任务协议**：队列 `agent:tasks` 的元素是 JSON 字符串，字段：
   - `id`：任务 ID（回写结果用）
   - `type`：`noop` | `sleep` | `echo`（真实业务可扩展为 `research`/`pdf`/`rag_ingest`）
   - `payload`：任务参数
   处理结果写入 `agent:results`（生产可换成回调 API / 数据库）。

4. **可观测**：每条任务的耗时与结果写入 stdout（K8s 侧由 Promtail/Loki 采集），
   队列长度直接作为 KEDA 的扩缩指标（见 optional/worker-deployment.yaml）。
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

READY_FILE = Path("/tmp/worker.ready")
DRAINING_FILE = Path("/tmp/worker.draining")

QUEUE = os.getenv("WORKER_QUEUE", "agent:tasks")
RESULT_QUEUE = os.getenv("WORKER_RESULT_QUEUE", "agent:results")
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "8"))
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [worker] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("queue_worker")


class MiniRedis:
    """最小 RESP 客户端：只实现 worker 需要的命令（AUTH / SELECT / PING / BRPOP / LPUSH / LLEN）。

    为什么不用 redis-py：镜像里没有该依赖，而 worker 只需要 3~4 个命令，
    40 行协议实现比新增依赖更可控（也避免为了 worker 单独重建镜像）。
    """

    def __init__(self, host: str, port: int, password: str | None, db: int, timeout: float = 35.0):
        self.host, self.port, self.password, self.db = host, port, password, db
        self.timeout = timeout
        self.sock: socket.socket | None = None

    # ---- 连接管理（带自动重连：Redis 重启后 worker 不能僵死） ----
    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.password:
            self._command("AUTH", self.password)
        if self.db:
            self._command("SELECT", str(self.db))

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _ensure(self) -> None:
        if self.sock is None:
            self.connect()

    # ---- 协议编解码 ----
    @staticmethod
    def _encode(*args: str) -> bytes:
        out = [f"*{len(args)}\r\n".encode()]
        for a in args:
            b = a.encode()
            out.append(f"${len(b)}\r\n".encode() + b + b"\r\n")
        return b"".join(out)

    def _read_line(self) -> bytes:
        assert self.sock is not None
        buf = bytearray()
        while not buf.endswith(b"\r\n"):
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("connection closed by redis")
            buf += chunk
        return bytes(buf[:-2])

    def _read_reply(self):
        assert self.sock is not None
        line = self._read_line()
        prefix, rest = line[:1], line[1:]
        if prefix == b"+":
            return rest.decode()
        if prefix == b"-":  # 错误
            raise RuntimeError(rest.decode())
        if prefix == b":":
            return int(rest)
        if prefix == b"$":  # bulk string
            n = int(rest)
            if n == -1:
                return None
            data = b""
            while len(data) < n + 2:
                data += self.sock.recv(n + 2 - len(data))
            return data[:n].decode()
        if prefix == b"*":  # array
            n = int(rest)
            if n == -1:
                return None
            return [self._read_reply() for _ in range(n)]
        raise RuntimeError(f"unexpected reply: {line!r}")

    def _command(self, *args: str):
        self.sock.sendall(self._encode(*args))
        return self._read_reply()

    # ---- 业务命令 ----
    def ping(self) -> bool:
        self._ensure()
        return self._command("PING") == "PONG"

    def brpop(self, key: str, timeout: int = 5):
        self._ensure()
        try:
            return self._command("BRPOP", key, str(timeout))
        except (ConnectionError, socket.timeout):
            self.close()
            raise

    def lpush(self, key: str, value: str) -> int:
        self._ensure()
        return int(self._command("LPUSH", key, value))


def parse_redis_url(url: str) -> tuple[str, int, str | None, int]:
    u = urlparse(url)
    return (u.hostname or "127.0.0.1", u.port or 6379, u.password, int((u.path or "/0").strip("/") or 0))


def handle_task(task: dict) -> dict:
    """任务处理：这里实现 3 种可验证的类型，真实业务替换为 research/pdf/rag_ingest 即可。"""
    ttype = task.get("type", "noop")
    payload = task.get("payload") or {}
    started = time.time()

    if ttype == "sleep":
        time.sleep(min(float(payload.get("seconds", 1)), 30))
        output = {"slept": payload.get("seconds", 1)}
    elif ttype == "echo":
        output = {"echo": payload.get("text", "")}
    else:  # noop：用于验证扩缩容链路
        output = {"ok": True}

    return {
        "id": task.get("id"),
        "type": ttype,
        "status": "done",
        "duration_ms": round((time.time() - started) * 1000, 2),
        "output": output,
        "worker": os.getenv("POD_NAME", socket.gethostname()),
    }


def main() -> int:
    host, port, password, db = parse_redis_url(REDIS_URL)
    log.info("启动 worker：queue=%s redis=%s:%s/%s concurrency=%s", QUEUE, host, port, db, CONCURRENCY)

    stop = {"flag": False, "draining": False}

    def _on_term(signum, _frame):
        log.info("收到信号 %s → 进入 draining（不再取新任务，做完在途任务再退出）", signum)
        stop["flag"] = True
        stop["draining"] = True
        DRAINING_FILE.touch()

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    r = MiniRedis(host, port, password, db)

    # 等待 Redis 可连接后再声明就绪（否则 readinessProbe 直接失败）
    for attempt in range(60):
        try:
            r.ping()
            break
        except Exception as e:  # noqa: BLE001
            log.warning("等待 Redis 就绪（第 %s 次）：%s", attempt + 1, e)
            time.sleep(2)
    else:
        log.error("Redis 不可达，退出")
        return 1

    READY_FILE.touch()
    log.info("worker 就绪（%s 已创建）", READY_FILE)

    inflight = 0
    while not stop["flag"]:
        try:
            item = r.brpop(QUEUE, timeout=5)
        except socket.timeout:
            continue
        except Exception as e:  # noqa: BLE001
            log.warning("BRPOP 失败，2s 后重连：%s", e)
            r.close()
            time.sleep(2)
            continue

        if not item:  # 超时无任务
            continue

        _, raw = item
        try:
            task = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("非法任务负载，丢弃：%.120s", raw)
            continue

        inflight += 1
        try:
            result = handle_task(task)
            log.info("任务完成 id=%s type=%s 耗时=%sms", result["id"], result["type"], result["duration_ms"])
            try:
                r.lpush(RESULT_QUEUE, json.dumps(result, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                log.warning("结果回写失败（不影响消费）：%s", e)
        except Exception as e:  # noqa: BLE001
            log.exception("任务处理异常 id=%s：%s", task.get("id"), e)
            try:
                r.lpush(RESULT_QUEUE, json.dumps({"id": task.get("id"), "status": "failed", "error": str(e)}))
            except Exception:  # noqa: BLE001
                pass
        finally:
            inflight -= 1

    # draining：等在途任务收尾（preStop 已额外 sleep，双保险）
    deadline = time.time() + 60
    while inflight > 0 and time.time() < deadline:
        log.info("draining：等待 %s 个在途任务完成", inflight)
        time.sleep(1)

    r.close()
    log.info("worker 退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
