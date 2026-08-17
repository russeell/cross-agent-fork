"""Core: session models, ref resolution, active-session detection, atomic writes."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from caf.i18n import t as _t


class CafxError(Exception):
    """Actionable error with a next-step hint (uv/cargo style)."""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------- data models


@dataclass
class ToolSummary:
    name: str
    status: str = "ok"
    file: Optional[str] = None


@dataclass
class Turn:
    seq: int
    role: str  # "user" | "assistant"
    text: str
    tools: list[ToolSummary] = field(default_factory=list)


@dataclass
class SessionMeta:
    provider_id: str
    session_id: str
    title: str = ""
    project_dir: Optional[str] = None
    source_path: Optional[str] = None
    turns: int = 0
    created_at: float = 0.0
    last_active_at: float = 0.0
    parent_ref: Optional[str] = None  # native lineage: e.g. "codex:<id>" / "cc:<id>" / "dsh:session-..."


@dataclass
class SessionIR:
    """Canonical IR (v0.1 minimal): whole-session text turns + tool summaries."""

    session: SessionMeta
    turns: list[Turn]
    modified: bool = False  # turns were sliced/injected -> writers must render IR, not the source file


# ---------------------------------------------------------------- utilities


def atomic_write(path: Path, text: str) -> None:
    """Atomic write: temp + rename, avoids partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path):
    """Yield JSONL lines, tolerating bad lines and truncated tails."""
    if not path.is_file():
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def disp_width(text: str) -> int:
    """Display width: CJK and other full-width chars count as 2 (dependency-free wcwidth)."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def truncate(text: str, width: int = 34) -> str:
    """Truncate by display width: collapse whitespace, append '...' (threads.title may be a full first message)."""
    text = " ".join(text.split())
    if disp_width(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2E7F else 1
        if used + cw > width - 1:
            break
        out += ch
        used += cw
    return out + "…"


def encode_cwd(path: str) -> str:
    """Claude Code project-dir encoding (verified): ASCII alnum kept, every other char -> '-'.

    Verified: /Users/russeell/Documents/开源项目开发/jobfindsme
      -> -Users-russeell-Documents--------jobfindsme (one '-' per CJK char)
    """
    return "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in path)


def parse_session_ref(ref: str, adapters) -> tuple[str, str]:
    """'cc:9f3a' / 'codex:last' -> (agent_id, sid); bare ids auto-detect the owner."""
    if ":" in ref:
        agent, _, sid = ref.partition(":")
        return agent, sid
    for adapter in adapters:
        if adapter.find_session(ref):
            return adapter.agent_id, ref
    raise CafxError(_t(f"Session not found: {ref}", f"未找到会话 {ref}"), hint="caf list --all")


def detect_active_agent() -> Optional[str]:
    """Detect the foreground agent via ps (iterm-agent-fork approach)."""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,tty=,stat=,command="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        _pid, tty, stat, cmd = parts
        if tty == "??" or "+" not in stat:
            continue
        tokens = cmd.split()
        base = Path(tokens[0]).name if tokens else ""
        if base == "codex" or "/codex" in cmd:
            return "codex"
        if base == "claude" or "/claude" in cmd:
            return "cc"
    return None


def pick_recent_session(adapters, project_dir: Optional[str] = None) -> Optional[SessionMeta]:
    """Pick the most recent non-empty session; prefer project_dir when given (empty-session noise filter)."""
    best: Optional[SessionMeta] = None
    for adapter in adapters:
        scan = getattr(adapter, "scan_cached", adapter.scan_sessions)
        for meta in scan():
            if meta.turns == 0:
                continue
            if meta.project_dir and not os.path.isdir(meta.project_dir):
                continue  # sessions whose working directory is gone cannot be forked
                          # (the official importer requires cwd)
            if project_dir and meta.project_dir and meta.project_dir != project_dir:
                continue
            if best is None or meta.last_active_at > best.last_active_at:
                best = meta
    return best


def slice_turns(turns: list[Turn], at: int, boundary: str = "through") -> tuple[list[Turn], Optional[str]]:
    """Slice IR turns by user-message sequence (opencode before/through model).

    - `--at N --through` (default): include user N and its completed assistant reply
    - `--at N --before`: stop strictly before user N (equivalent to through N-1)
    - Unfinished turn N (no assistant after user N): through -> cut to the last complete turn + warn
    Returns (sliced turns, warning or None).
    """
    if at < 1:
        raise CafxError(_t(f"Invalid fork point: --at {at}", f"无效分叉点: --at {at}"),
                        hint=_t("--at must be >= 1", "--at 必须 ≥ 1"))
    if boundary == "before":
        return slice_turns(turns, at - 1, "through") if at > 1 else _empty_slice(at, boundary)

    idx_user: Optional[int] = None
    user_count = 0
    for i, turn in enumerate(turns):
        if turn.role == "user":
            user_count += 1
            if user_count == at:
                idx_user = i
                break
    if idx_user is None:
        raise CafxError(
            _t(f"Turn {at} does not exist (session has {user_count} user messages)",
              f"第 {at} 轮不存在（会话共 {user_count} 个用户消息）"),
            hint=_t("Check turns with caf list", "caf list 查看轮数"),
        )

    end = idx_user
    warning: Optional[str] = None
    if idx_user + 1 < len(turns) and turns[idx_user + 1].role == "assistant":
        end = idx_user + 1
    elif idx_user == len(turns) - 1:
        # unfinished turn at the end of the session (DSH rule: only fork completed turns)
        end = idx_user - 1
        while end >= 0 and turns[end].role != "assistant":
            end -= 1
        if end < 0:
            raise CafxError(
                _t(f"No completed turns before turn {at}", f"第 {at} 轮之前没有完成的轮次可 fork"),
                hint=_t("Pick an earlier --at", "--at 换一个更早的分叉点"),
            )
        warning = _t(f"Turn {at} is unfinished; truncated to turn {at - 1}",
                    f"第 {at} 轮未完成，已截断到第 {at - 1} 轮")
    # consecutive user messages (injections/multi-part input): include only user N;
    # its reply belongs to a later turn
    return turns[: end + 1], warning


def _empty_slice(at: int, boundary: str):
    raise CafxError(_t(f"Empty result (--at {at} --{boundary})",
                      f"结果为空（--at {at} --{boundary}）"),
                    hint=_t("--at must be >= 1 (--before 1 has nothing to fork)",
                           "--at 必须 ≥ 1（--before 1 无内容可 fork）"))


def with_tool_lines(text: str, tools: list[ToolSummary]) -> str:
    """Append tool summaries to a turn's text as one line per tool."""
    for tool in tools:
        line = f"[{_t('tool', '工具')}] {tool.name} · {tool.status}"
        if tool.file:
            line += f" · {tool.file}"
        text = f"{text}\n{line}" if text else line
    return text
