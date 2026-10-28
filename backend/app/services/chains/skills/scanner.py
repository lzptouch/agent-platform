"""插件/技能静态扫描规则集（S6 / WP-6.5）。

七项规则：可执行脚本、网络调用、删除/递归、敏感路径、硬编码凭据、代码混淆、体积异常。

分级：``low / medium / high / critical``；处置策略：
``low`` 直接装；``medium`` 提示；``high``/``critical`` **默认拒绝**（需显式确认）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LEVELS = ("low", "medium", "high", "critical")
_ORDER = {lv: i for i, lv in enumerate(LEVELS)}

#: 敏感路径（凭据 / 配置 / 系统目录）
SENSITIVE_PATTERNS = (
    r"\.ssh", r"\.aws", r"\.gnupg", r"\.kube", r"id_rsa", r"\.pem\b", r"\.env\b",
    r"credentials", r"secrets?[/\\]", r"AppData.*(Roaming|Local)",
    r"/etc/(passwd|shadow)", r"C:\\\\Windows",
)

#: 网络调用
NETWORK_PATTERNS = (
    r"\brequests\.(get|post|put|delete|patch)\b",
    r"\bhttpx\.", r"\burllib\.request\b", r"\baiohttp\b",
    r"\bfetch\s*\(", r"https?://",
    r"\bcurl\b", r"\bwget\b", r"Invoke-WebRequest",
)

#: 删除 / 递归
DELETE_PATTERNS = (
    r"\bshutil\.rmtree\b", r"\bos\.remove\b", r"\bos\.unlink\b", r"\bos\.rmdir\b",
    r"\brm\s+-rf\b", r"\brmdir\s+/s\b", r"\bdel\s+/[sq]\b",
    r"\bRemove-Item\b.*-Recurse",
)

#: 硬编码凭据
CREDENTIAL_PATTERNS = (
    r"sk-[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
)

#: 代码混淆特征
OBFUSCATION_PATTERNS = (
    r"\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){8,}",   # 大量 \x 转义
    r"[A-Za-z0-9+/]{120,}={0,2}",                      # 超长 base64
    r"eval\s*\(\s*(?:atob|base64|unescape)",           # eval + 解码
    r"exec\s*\(\s*base64",
)

#: 可执行脚本（按扩展名）
EXECUTABLE_EXT = {".py", ".sh", ".bat", ".cmd", ".ps1", ".exe", ".dll", ".so", ".js", ".mjs"}


@dataclass
class ScanFinding:
    """一条扫描发现。"""

    rule: str
    level: str
    reason: str
    path: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "level": self.level,
            "reason": self.reason,
            "path": self.path,
        }


@dataclass
class ScanResult:
    """扫描结果。"""

    level: str = "low"
    findings: list[ScanFinding] = field(default_factory=list)
    scanned_files: int = 0
    total_bytes: int = 0

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "findings": [f.as_dict() for f in self.findings],
            "scanned_files": self.scanned_files,
            "total_bytes": self.total_bytes,
            # 与 needs_confirmation / should_reject 保持一致：
            #   medium → 需提示确认；high/critical → 默认拒绝
            "requires_confirmation": self.level in ("medium", "high", "critical"),
            "rejected_by_default": self.level in ("high", "critical"),
        }


def _max_level(current: str, candidate: str) -> str:
    return candidate if _ORDER[candidate] > _ORDER[current] else current


def scan_text(text: str, path: str = "") -> list[ScanFinding]:
    """对单个文本做规则匹配。"""
    findings: list[ScanFinding] = []
    for pat in CREDENTIAL_PATTERNS:
        if re.search(pat, text):
            findings.append(ScanFinding("hardcoded_credential", "critical",
                                        f"命中硬编码凭据模式: {pat[:28]}", path))
            break
    for pat in OBFUSCATION_PATTERNS:
        if re.search(pat, text):
            findings.append(ScanFinding("obfuscation", "high",
                                        f"命中代码混淆特征: {pat[:28]}", path))
            break
    for pat in DELETE_PATTERNS:
        if re.search(pat, text):
            findings.append(ScanFinding("delete_or_recursive", "high",
                                        f"命中删除/递归操作: {pat[:28]}", path))
            break
    for pat in NETWORK_PATTERNS:
        if re.search(pat, text):
            findings.append(ScanFinding("network_call", "medium",
                                        f"命中网络调用: {pat[:28]}", path))
            break
    for pat in SENSITIVE_PATTERNS:
        if re.search(pat, text):
            findings.append(ScanFinding("sensitive_path", "high",
                                        f"命中敏感路径: {pat[:28]}", path))
            break
    return findings


def scan_directory(root: Path, *, max_total_bytes: int = 50 * 1024 * 1024) -> ScanResult:
    """扫描一个目录（技能包 / 插件包）。"""
    result = ScanResult()
    if not root.exists():
        return result
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        result.scanned_files += 1
        rel = str(path.relative_to(root))
        if path.suffix.lower() in EXECUTABLE_EXT:
            result.findings.append(ScanFinding(
                "executable_script", "medium",
                f"包含可执行脚本: {path.suffix}", rel,
            ))
            result.level = _max_level(result.level, "medium")
        if path.suffix.lower() in {".md", ".txt", ".py", ".sh", ".json", ".yaml", ".yml", ".js"}:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for finding in scan_text(text, rel):
                result.findings.append(finding)
                result.level = _max_level(result.level, finding.level)
    result.total_bytes = total
    if total > max_total_bytes:
        result.findings.append(ScanFinding(
            "size_anomaly", "medium",
            f"体积异常：{total} 字节 > {max_total_bytes}", "",
        ))
        result.level = _max_level(result.level, "medium")
    return result


def should_reject(scan: ScanResult) -> bool:
    """high/critical **默认拒绝**（需显式确认才能装）。"""
    return scan.level in ("high", "critical")


def needs_confirmation(scan: ScanResult) -> bool:
    """medium 及以上需要提示（high/critical 需要显式确认）。"""
    return scan.level in ("medium", "high", "critical")
