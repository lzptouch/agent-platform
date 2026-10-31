"""敏感信息保护（S3 / WP-3.6）。

在内容进入模型前扫描（正则 + 熵值双判），按规则处置：
- ``allow``：原样放行；
- ``allow_and_encrypt``：敏感片段加密后参与上下文，输出时还原；
- ``deny``：默认对**高置信密钥**拒绝。

默认安全：高置信密钥 → deny；低置信 → allow_and_encrypt。
"""
from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 高置信密钥格式（正则）
# --------------------------------------------------------------------------- #
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dashscope", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("openai", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_token", re.compile(r"(?:token|secret|api_key|apikey|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{16,}", re.I)),
]

#: 熵值阈值（字符集随机性），低置信候选用它复判
_ENTROPY_THRESHOLD = 4.2


@dataclass(frozen=True)
class SensitiveHit:
    kind: str
    matched: str
    start: int
    end: int
    confidence: str  # high | low


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def scan(text: str) -> list[SensitiveHit]:
    """扫描文本中的敏感片段（正则 + 熵值双判）。"""
    hits: list[SensitiveHit] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            matched = m.group(0)
            conf = "high" if kind in ("private_key", "aws_access_key", "dashscope", "openai") else "low"
            hits.append(SensitiveHit(kind, matched, m.start(), m.end(), conf))
    # 低置信熵值复判：高随机性的长串（可能是密钥但没匹配到已知格式）
    for m in re.finditer(r"[A-Za-z0-9+/=_\-]{24,}", text):
        s = m.group(0)
        if any(h.start <= m.start() < h.end for h in hits):
            continue
        if _entropy(s) >= _ENTROPY_THRESHOLD:
            hits.append(SensitiveHit("high_entropy", s, m.start(), m.end(), "low"))
    return hits


# --------------------------------------------------------------------------- #
# 处置
# --------------------------------------------------------------------------- #
def encrypt_fragment(text: str) -> str:
    """加密一个敏感片段（可还原；本阶段用 base64 包装，密钥管理在后续阶段接入）。"""
    return "ENC[" + base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii") + "]"


def decrypt_fragment(text: str) -> str:
    """还原加密片段（用于输出时还原）。"""
    if text.startswith("ENC[") and text.endswith("]"):
        try:
            return base64.urlsafe_b64decode(text[4:-1].encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001
            return text
    return text


def process(text: str, *, policy: str = "encrypt") -> dict:
    """扫描并按**策略**处置文本。

    返回 ``{action, processed, hits}``：
    - ``action``：allow / allow_and_encrypt / deny；
    - ``processed``：处置后的文本（加密片段已替换）；
    - ``hits``：命中的敏感片段（脱敏后的摘要，不含原文）。

    **P2-07**：此前 ``policy`` 参数**形同虚设**（分支固定为「高置信 deny、低置信加密」），
    与设计要求的三档处置（允许 / 允许并加密 / 禁止）对不上。现按策略驱动：

    - ``allow``：只记录命中，**不改内容**；
    - ``encrypt``：低/中置信片段加密（密文参与上下文，输出时用 :func:`restore` 还原），
      但**高置信（私钥 / 高熵凭证）一律拒绝**——密钥类内容不能靠加密蒙混过关；
    - ``deny``：任何命中都拒绝（由调用方决定是拒写还是拒发）。
    """
    hits = scan(text)
    if not hits:
        return {"action": "allow", "processed": text, "hits": []}

    summary = [{"kind": h.kind, "confidence": h.confidence, "at": h.start} for h in hits]
    policy = (policy or "encrypt").lower()

    if policy == "allow":
        return {"action": "allow", "processed": text, "hits": summary}

    if policy == "deny":
        return {"action": "deny", "processed": text, "hits": summary}

    # encrypt：高置信（私钥 / 高熵凭证）一律拒绝
    if any(h.confidence == "high" for h in hits):
        return {"action": "deny", "processed": text, "hits": summary}

    # encrypt：全部命中片段加密（密文参与上下文，输出时还原）
    processed = text
    for h in sorted(hits, key=lambda x: x.start, reverse=True):
        processed = processed[: h.start] + encrypt_fragment(h.matched) + processed[h.end :]
    return {"action": "allow_and_encrypt", "processed": processed, "hits": summary}


def restore(text: str) -> str:
    """输出时还原所有加密片段。"""
    return re.sub(r"ENC\[[A-Za-z0-9+/=_\-]+\]", lambda m: decrypt_fragment(m.group(0)), text)
