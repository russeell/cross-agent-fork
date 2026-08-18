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
class Turn:
    role: str  # "user" | "assistant"
    text: str


@dataclass
class SessionMeta:
    agent_id: str
    session_id: str
    title: str = ""
    project_dir: str | None = None
    source_path: str | None = None
    turns: int = 0
    last_active_at: float = 0.0


@dataclass
class ForkSnapshot:
    """Minimal portable fork snapshot, not a universal session schema."""

    session: SessionMeta
    turns: list[Turn]
    modified: bool = False  # sliced/injected snapshots must be rendered, not copied
    unfinished_turns: set[int] = field(default_factory=set)
    tail_open: bool = False  # last turn is not durably closed (mid-append/crash)


# ---------------------------------------------------------------- utilities


def atomic_write(path: Path, text: str) -> None:
    """Atomic write: temp + rename, avoids partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path):
    """Yield JSONL lines, tolerating bad lines and truncated tails.

    Lenient reader for scans: one corrupt session must not break discovery.
    """
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


def read_stable_jsonl(path: Path):
    """Yield complete JSONL records from a bounded point-in-time snapshot.

    Contract: *tail tolerant, interior strict, snapshot bounded.*

    - the file size is fixed first (fstat), so a source agent appending while we
      read cannot leak records across the boundary;
    - complete records are parsed; an incomplete final line (no trailing newline,
      i.e. a mid-append tail) is dropped;
    - any malformed *interior* line is a hard error — never silently skip it.
    """
    if not path.is_file():
        return
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        data = f.read(size)
    lines = data.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if not line.endswith(b"\n"):
            continue  # incomplete final line: the source was still appending
        try:
            yield json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise CafError(
                f"Malformed session record in {path} at line {i + 1}",
                hint="The source session file is corrupt; pick another session",
            ) from e


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


def slice_turns(
    turns: list[Turn], at: int, unfinished_turns: set[int] | None = None
) -> list[Turn]:
    """Slice a snapshot by user-message sequence: include user N through its reply.
    A requested turn without an assistant reply fails instead of moving the boundary."""
    if at < 1:
        raise CafError(f"Invalid fork point: --at {at}", hint="--at must be >= 1")
    if unfinished_turns and at in unfinished_turns:
        hint = (
            f"Use --at {at - 1}, or fork the whole current session (no --at)."
            if at > 1
            else "Fork the whole current session (no --at), or choose a completed turn."
        )
        raise CafError(f"Turn {at} is unfinished.", hint=hint)

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
    return turns[: end + 1]


def append_evidence(text: str, block: str) -> str:
    """Append already-portable evidence to a turn without introducing a tool schema."""
    if not block:
        return text
    return f"{text}\n{block}" if text else block


def tool_call_text(name: str, arguments: str = "") -> str:
    """Portable text for an observed tool call; no status is invented."""
    text = f"[tool] {name}"
    if arguments:
        text += f"\nargs: {arguments}"
    return text


def tool_result_text(name: str, output: str, is_error: bool) -> str:
    """Portable text for an observed tool result."""
    status = "error" if is_error else "ok"
    text = f"[tool result] {name} · {status}"
    if output:
        text += f"\n{output}"
    return text
