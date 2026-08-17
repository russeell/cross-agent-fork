"""Claude Code adapter: read CC JSONL (whole session) + write the CC envelope (file-level)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from caf.adapters import Adapter
from caf.i18n import t as _t
from caf.core import (
    CafxError,
    SessionIR,
    SessionMeta,
    ToolSummary,
    Turn,
    atomic_write,
    encode_cwd,
    read_jsonl,
    with_tool_lines,
)


def _projects_dir() -> Path:
    return Path(os.environ.get("CAF_CC_PROJECTS", str(Path.home() / ".claude" / "projects")))


def cc_projects_dir() -> Path:
    """CC session store root (used by external modules such as the codex bridge)."""
    return _projects_dir()


def _text_blocks(message) -> Optional[str]:
    """Extract text from a CC message.content (tolerates string / list / absent)."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts) if parts else None


def _tool_blocks(message) -> list[ToolSummary]:
    content = message.get("content") if isinstance(message, dict) else None
    out = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        inp = block.get("input") or {}
        file = None
        if isinstance(inp, dict):
            for key in ("file_path", "path", "file", "file_name"):
                val = inp.get(key)
                if isinstance(val, str):
                    file = val
                    break
        out.append(ToolSummary(str(block.get("name", "tool")), "ok", file))
    return out


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_cc_lines(ir: SessionIR, sid: str) -> list[str]:
    """Build CC envelope JSONL lines (queue-operation + summary + parentUuid chain + tool summaries)."""
    cwd = ir.session.project_dir or os.getcwd()
    now = _ts()
    lines: list[dict] = [
        {"type": "queue-operation", "operation": "add-context", "timestamp": now, "sessionId": sid, "content": []},
        {"type": "queue-operation", "operation": "update-context", "timestamp": now, "sessionId": sid, "content": []},
        {"type": "summary", "summary": ir.session.title or "caf fork", "leafUuid": None,
         "cwd": cwd, "sessionId": sid, "version": "2.1.187"},
    ]
    parent: Optional[str] = None
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

    def detect(self) -> bool:
        return _projects_dir().is_dir()

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

    def _meta_from_file(self, path: Path) -> Optional[SessionMeta]:
        title = ""
        first_user = ""
        cwd: Optional[str] = None
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
            first_line = first_user.splitlines()[0] if first_user.splitlines() else first_user
            title = first_line[:80]
        stat = path.stat()
        return SessionMeta(
            provider_id=self.agent_id,
            session_id=path.stem,
            title=title,
            project_dir=cwd,
            source_path=str(path),
            turns=turns,
            created_at=stat.st_ctime,
            last_active_at=stat.st_mtime,
        )

    def load_session(self, sid: str) -> SessionIR:
        meta = self.find_session(sid)
        if not meta:
            raise CafxError(_t(f"Claude Code session not found: {sid}",
                              f"未找到 Claude Code 会话 {sid}"), hint="caf list --all")
        turns: list[Turn] = []
        seq = 0
        for ev in read_jsonl(Path(meta.source_path)):
            t = ev.get("type")
            if t == "user":
                msg = ev.get("message") or {}
                if ev.get("isMeta") or msg.get("role") != "user":
                    continue
                text = _text_blocks(msg)
                if text is None:
                    continue
                seq += 1
                turns.append(Turn(seq, "user", text))
            elif t == "assistant":
                msg = ev.get("message") or {}
                text = _text_blocks(msg) or ""
                tools = _tool_blocks(msg)
                if text or tools:
                    seq += 1
                    turns.append(Turn(seq, "assistant", text, tools))
        return SessionIR(meta, turns)

    def resume_command(self, sid: str, project_dir: Optional[str]) -> str:
        prefix = f"cd {shlex.quote(project_dir)} && " if project_dir else ""
        return f"{prefix}claude --resume {sid}"

    def write(self, ir: SessionIR) -> str:
        """Write a native CC JSONL envelope: queue-operation prefix + parentUuid chain."""
        cwd = ir.session.project_dir or os.getcwd()
        target_dir = _projects_dir() / encode_cwd(cwd)
        target_dir.mkdir(parents=True, exist_ok=True)
        sid = str(uuid4())
        path = target_dir / f"{sid}.jsonl"
        atomic_write(path, "\n".join(render_cc_lines(ir, sid)) + "\n")

        # verify: read back and roll back on failure
        if self._meta_from_file(path) is None:
            path.unlink(missing_ok=True)
            raise CafxError(_t("Write verification failed; rolled back", "写入校验失败，已回滚"))
        self.invalidate()
        return sid

    def written_path(self, sid: str, project_dir: Optional[str]) -> Optional[Path]:
        cwd = project_dir or os.getcwd()
        p = _projects_dir() / encode_cwd(cwd) / f"{sid}.jsonl"
        return p if p.is_file() else None

    def undo_command(self, sid: str, project_dir: Optional[str]) -> str:
        p = self.written_path(sid, project_dir)
        return f"rm {shlex.quote(str(p))}" if p else ""


def _cc_version_probe() -> str:
    """Probe the installed claude CLI version (used by doctor)."""
    claude = shutil.which("claude")
    if not claude:
        return "off"
    try:
        import subprocess
        out = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
        return out.split()[0] if out else ""
    except Exception:
        return ""
