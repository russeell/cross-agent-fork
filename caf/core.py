"""Core: session models, ref resolution, deterministic source pick, atomic writes."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


class CafError(Exception):
    """Actionable error with a next-step hint."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------- data models


@dataclass
class ToolEvidence:
    name: str
    status: str = "unknown"  # "unknown" | "ok" | "error" — never guessed, only observed
    call_id: str = ""
    arguments: str = ""  # raw arguments (JSON string or text), truncated on render
    result: str = ""  # tool output text, truncated on render


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    tools: list[ToolEvidence] = field(default_factory=list)


@dataclass
class SessionMeta:
    provider_id: str
    session_id: str
    title: str = ""
    project_dir: str | None = None
    source_path: str | None = None
    turns: int = 0
    last_active_at: float = 0.0


@dataclass
class SessionIR:
    """Minimal portable fork snapshot, not a universal session schema."""

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


def parse_session_ref(ref: str, adapters) -> tuple[str, str]:
    """'cc:9f3a' / 'codex:last' -> (agent_id, sid); bare ids auto-detect the owner (ambiguity -> error)."""
    if ":" in ref:
        agent, _, sid = ref.partition(":")
        return agent, sid
    found = []
    for adapter in adapters:
        if not adapter.read_ready():
            continue  # only probe adapters that can actually read sessions
        if adapter.find_session(ref):
            found.append(adapter)
    if len(found) > 1:
        raise CafError(
            f"Session id {ref} matches multiple agents",
            hint="Use the agent: prefix (e.g. cc:<id>)",
        )
    if found:
        return found[0].agent_id, ref
    raise CafError(f"Session not found: {ref}", hint="caf list --all")


def pick_recent_session(adapters, project_dir: str | None = None) -> SessionMeta | None:
    """Pick the most recent forkable session; prefer project_dir when given."""
    best: SessionMeta | None = None
    for adapter in adapters:
        for meta in adapter.scan_cached():
            if meta.turns == 0:
                continue
            if not meta.project_dir or not os.path.isdir(meta.project_dir):
                continue  # a fork must carry a real cwd; never invent one
            if project_dir is not None and os.path.realpath(
                meta.project_dir
            ) != os.path.realpath(project_dir):
                continue
            if best is None or meta.last_active_at > best.last_active_at:
                best = meta
    return best


def slice_turns(turns: list[Turn], at: int) -> tuple[list[Turn], str | None]:
    """Slice IR turns by user-message sequence: include user N and everything up to the next user.
    A requested turn without an assistant reply fails instead of moving the boundary."""
    if at < 1:
        raise CafError(f"Invalid fork point: --at {at}", hint="--at must be >= 1")

    idx_user: int | None = None
    user_count = 0
    for i, turn in enumerate(turns):
        if turn.role == "user":
            user_count += 1
            if user_count == at:
                idx_user = i
                break
    if idx_user is None:
        raise CafError(
            f"Turn {at} does not exist (session has {user_count} user messages)",
            hint="Check turns with caf list",
        )

    end = idx_user
    while end + 1 < len(turns) and turns[end + 1].role != "user":
        end += 1  # everything after user N up to the next user belongs to turn N
    segment = turns[idx_user : end + 1]
    if not any(turn.role == "assistant" for turn in segment):
        # never silently move the fork point: an unfinished turn must be explicit
        hint = (
            f"Use --at {at - 1}, or fork the whole current session (no --at)."
            if at > 1
            else "Fork the whole current session (no --at), or choose a completed turn."
        )
        raise CafError(
            f"Turn {at} is unfinished (the session ends there without a reply).",
            hint=hint,
        )
    return turns[: end + 1], None


def with_tool_lines(text: str, tools: list[ToolEvidence]) -> str:
    """Render tool evidence into a turn's text: one summary line per tool, plus the
    arguments and result the next agent needs to understand what happened."""
    for tool in tools:
        line = f"[tool] {tool.name} · {tool.status}"
        text = f"{text}\n{line}" if text else line
        if tool.arguments:
            text += f"\n  args: {tool.arguments[:500]}"
        if tool.result:
            text += f"\n[tool-result] {tool.result[:2000]}"
    return text
