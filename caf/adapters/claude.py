"""Claude Code adapter: read CC JSONL (whole session) + write the CC envelope (file-level)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from caf.adapters import Adapter
from caf.core import (
    CafError,
    SessionIR,
    SessionMeta,
    ToolEvidence,
    Turn,
    atomic_write,
    read_jsonl,
    with_tool_lines,
)


def _projects_dir() -> Path:
    return Path(
        os.environ.get("CAF_CC_PROJECTS", str(Path.home() / ".claude" / "projects"))
    )


def cc_projects_dir() -> Path:
    """CC session store root (used by external modules such as the codex bridge)."""
    return _projects_dir()


def encode_cwd(path: str) -> str:
    """CC project-dir encoding: ASCII alnum kept, every other char -> '-' (one '-' per CJK char)."""
    return "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in path)


def _text_blocks(message) -> str | None:
    """Extract text from a CC message.content (tolerates string / list / absent)."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
    return "\n".join(parts) if parts else None


def _tool_blocks(message) -> list[ToolEvidence]:
    """tool_use blocks -> evidence (status stays unknown until the matching result arrives)."""
    content = message.get("content") if isinstance(message, dict) else None
    out = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        inp = block.get("input") or {}
        out.append(
            ToolEvidence(
                name=str(block.get("name", "tool")),
                call_id=str(block.get("id", "")),
                arguments=json.dumps(inp, ensure_ascii=False)
                if isinstance(inp, dict)
                else str(inp),
            )
        )
    return out


def _tool_results(message) -> dict[str, tuple[str, str]]:
    """tool_result blocks -> {tool_use_id: (result_text, status)}."""
    content = message.get("content") if isinstance(message, dict) else None
    out: dict[str, tuple[str, str]] = {}
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tid = str(block.get("tool_use_id", ""))
        if not tid:
            continue
        raw = block.get("content")
        text = (
            _text_blocks({"content": raw})
            if isinstance(raw, list)
            else (raw if isinstance(raw, str) else "")
        )
        status = "error" if block.get("is_error") else "ok"
        out[tid] = (text or "", status)
    return out


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_cc_lines(ir: SessionIR, sid: str) -> list[str]:
    """Build CC envelope JSONL lines with text and portable tool evidence."""
    cwd = ir.session.project_dir
    if not cwd:
        raise CafError("Cannot fork: source working directory is unknown.")
    now = _ts()
    summary = {
        "type": "summary",
        "summary": ir.session.title or "caf fork",
        "leafUuid": None,
        "cwd": cwd,
        "sessionId": sid,
    }
    version = _cc_version()
    if version:
        summary["version"] = version
    lines: list[dict] = [
        {
            "type": "queue-operation",
            "operation": "add-context",
            "timestamp": now,
            "sessionId": sid,
            "content": [],
        },
        {
            "type": "queue-operation",
            "operation": "update-context",
            "timestamp": now,
            "sessionId": sid,
            "content": [],
        },
        summary,
    ]
    parent: str | None = None
    for turn in ir.turns:
        if not turn.text and not turn.tools:
            continue  # empty turns (no semantic content) must not enter the envelope
        text = with_tool_lines(turn.text, turn.tools)
        uid = str(uuid4())
        message = {
            "role": turn.role,
            "content": [{"type": "text", "text": text}] if text else [],
        }
        ev: dict = {
            "parentUuid": parent,
            "type": turn.role,
            "message": message,
            "uuid": uid,
            "timestamp": now,
            "cwd": cwd,
        }
        if turn.role == "user":
            ev["isMeta"] = False
        lines.append(ev)
        parent = uid
    return [json.dumps(line, ensure_ascii=False) for line in lines]


class ClaudeAdapter(Adapter):
    agent_id = "cc"
    display_name = "claude"

    def read_ready(self) -> bool:
        return _projects_dir().is_dir()

    def write_ready(self) -> bool:
        """Writing creates the store (mkdir), but resume needs the CLI installed."""
        return shutil.which("claude") is not None

    def store_version(self) -> str:
        return _cc_version_probe()

    def store_path(self) -> str:
        return "~/.claude/projects"

    def scan_sessions(self) -> list[SessionMeta]:
        out: list[SessionMeta] = []
        root = _projects_dir()
        if not root.is_dir():
            return out
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.jsonl")):
                meta = self._meta_from_file(f)
                if meta:
                    out.append(meta)
        return out

    def _meta_from_file(self, path: Path) -> SessionMeta | None:
        title = ""
        first_user = ""
        cwd: str | None = None
        turns = 0
        for ev in read_jsonl(path):
            t = ev.get("type")
            if t == "ai-title":
                # CC 2.1.x new format: {"type":"ai-title","aiTitle":"..."}
                v = ev.get("aiTitle")
                if isinstance(v, str) and v.strip():
                    title = v.strip()
            elif t == "summary" and not title and isinstance(ev.get("summary"), str):
                # legacy format: {"type":"summary","summary":"..."}
                title = ev["summary"]
            elif t == "user":
                msg = ev.get("message") or {}
                if msg.get("role") == "user" and not ev.get("isMeta"):
                    turns += 1
                    if not first_user:
                        text = _text_blocks(msg)
                        if text:
                            first_user = " ".join(text.split())
                    if not cwd and isinstance(ev.get("cwd"), str):
                        cwd = ev["cwd"]
        if not title and first_user:
            # no title: fall back to the first line of the first user message (same as
            # codex-plugin-cc's summarize_for_label)
            first_line = (
                first_user.splitlines()[0] if first_user.splitlines() else first_user
            )
            title = first_line[:80]
        stat = path.stat()
        return SessionMeta(
            provider_id=self.agent_id,
            session_id=path.stem,
            title=title,
            project_dir=cwd,
            source_path=str(path),
            turns=turns,
            last_active_at=stat.st_mtime,
        )

    def load_session(self, sid: str) -> SessionIR:
        meta = self.find_session(sid)
        if not meta:
            raise CafError(
                f"Claude Code session not found: {sid}", hint="caf list --all"
            )
        turns: list[Turn] = []
        for ev in read_jsonl(Path(meta.source_path)):
            t = ev.get("type")
            if t == "user":
                msg = ev.get("message") or {}
                if not ev.get("isMeta"):
                    if msg.get("role") != "user":
                        continue
                    text = _text_blocks(msg)
                    if text is None:
                        continue
                    turns.append(Turn("user", text))
                    continue
                # isMeta user message: tool_result blocks complete the previous assistant's tools
                if not turns or turns[-1].role != "assistant":
                    continue
                for tid, (result, status) in _tool_results(msg).items():
                    for tool in reversed(turns[-1].tools):
                        if tool.call_id == tid:
                            tool.result = result
                            tool.status = status
                            break
            elif t == "assistant":
                msg = ev.get("message") or {}
                text = _text_blocks(msg) or ""
                tools = _tool_blocks(msg)
                if text or tools:
                    turns.append(Turn("assistant", text, tools))
        return SessionIR(meta, turns)

    def resume_command(self, sid: str, project_dir: str | None) -> str:
        prefix = f"cd {shlex.quote(project_dir)} && " if project_dir else ""
        return f"{prefix}claude --resume {sid}"

    def write(self, ir: SessionIR) -> str:
        """Write a native CC JSONL envelope: queue-operation prefix + parentUuid chain."""
        cwd = ir.session.project_dir
        if not cwd or not os.path.isdir(cwd):
            raise CafError(
                "Cannot fork: source working directory is unknown or does not exist."
            )
        target_dir = _projects_dir() / encode_cwd(cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        sid = str(uuid4())
        path = target_dir / f"{sid}.jsonl"
        atomic_write(path, "\n".join(render_cc_lines(ir, sid)) + "\n")

        # verify: read back and roll back on failure
        if self._meta_from_file(path) is None:
            path.unlink(missing_ok=True)
            raise CafError("Write verification failed; rolled back")
        return sid


_CACHED_CC_VERSION: str | None = None


def _cc_version() -> str:
    """Return the installed CC version when known; never fabricate a version."""
    global _CACHED_CC_VERSION
    if _CACHED_CC_VERSION is None:
        _CACHED_CC_VERSION = _cc_version_probe()
    return _CACHED_CC_VERSION


def _cc_version_probe() -> str:
    """Probe the installed claude CLI version (used by doctor)."""
    claude = shutil.which("claude")
    if not claude:
        return "off"
    try:
        import subprocess

        out = subprocess.run(
            [claude, "--version"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return out.split()[0] if out else ""
    except Exception:
        return ""
