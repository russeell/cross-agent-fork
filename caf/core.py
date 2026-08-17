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
class ToolSummary:
    name: str
    status: str = "ok"
    file: str | None = None


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    tools: list[ToolSummary] = field(default_factory=list)


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
    """Pick the most recent non-empty session; prefer project_dir when given (empty-session noise filter)."""
    best: SessionMeta | None = None
    for adapter in adapters:
        for meta in adapter.scan_cached():
            if meta.turns == 0:
                continue
            if meta.project_dir and not os.path.isdir(meta.project_dir):
                continue  # sessions whose working directory is gone cannot be forked
                # (the official importer requires cwd)
            if project_dir is not None and meta.project_dir != project_dir:
                continue
            if best is None or meta.last_active_at > best.last_active_at:
                best = meta
    return best


def slice_turns(turns: list[Turn], at: int) -> tuple[list[Turn], str | None]:
    """Slice IR turns by user-message sequence: include user N and everything up to the next user.
    An unfinished final turn is cut to the last complete turn with a warning."""
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

    warning: str | None = None
    end = idx_user
    while end + 1 < len(turns) and turns[end + 1].role != "user":
        end += 1  # everything after user N up to the next user belongs to turn N
    if end == idx_user and idx_user == len(turns) - 1:
        # unfinished turn at the end of the session (DSH rule: only fork completed turns)
        end = idx_user - 1
        while end >= 0 and turns[end].role != "assistant":
            end -= 1
        if end < 0:
            raise CafError(
                f"No completed turns before turn {at}",
                hint="Pick an earlier --at",
            )
        warning = f"Turn {at} is unfinished; truncated to turn {at - 1}"
    return turns[: end + 1], warning


def with_tool_lines(text: str, tools: list[ToolSummary]) -> str:
    """Append tool summaries to a turn's text as one line per tool."""
    for tool in tools:
        line = f"[tool] {tool.name} · {tool.status}"
        if tool.file:
            line += f" · {tool.file}"
        text = f"{text}\n{line}" if text else line
    return text
