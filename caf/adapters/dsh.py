"""DeepSeek Harness (DSH) adapter: reads/writes zstd JSONL sessions under ~/.dsh/sessions.

Format (verified against @deepseek-ai/dsh-session-persistence-jsonl):
  ~/.dsh/sessions/<projectKey(cwd)>/session-<uuid>/session.jsonl.zstd
  line 1 header: {"type":"session","version":0,"id":"session-...","createdAt":ms,"cwd":...}
  following events: turn/start | user/message | assistant/message | tool/call | tool/result | turn/end ...
One zstd frame per JSON line; message events carry surfaceOp (seed validation requires it).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path
from uuid import uuid4

import zstandard as zstd

from caf.adapters import Adapter
from caf.core import (
    CafError,
    SessionIR,
    SessionMeta,
    ToolSummary,
    Turn,
    with_tool_lines,
)

_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def _root() -> Path:
    return Path(
        os.environ.get("CAF_DSH_SESSIONS", str(Path.home() / ".dsh" / "sessions"))
    )


def _dsh_home() -> Path:
    return Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))


def _zstd_decompress(data: bytes) -> bytes:
    """Decompress a multi-frame log: decompress() silently returns only the first frame,
    so walk frames one by one (DSH writes one frame per JSON line)."""
    dctx = zstd.ZstdDecompressor()
    out = bytearray()
    pos = 0
    while pos < len(data):
        dobj = dctx.decompressobj()
        out += dobj.decompress(data[pos:])
        consumed = len(data) - pos - len(dobj.unused_data)
        if consumed <= 0:
            raise zstd.ZstdError("no frame progress")
        pos += consumed
    return bytes(out)


def _zstd_compress_frames(chunks: list[bytes]) -> bytes:
    """Compress each chunk as its own zstd frame (DSH stores one frame per JSON line;
    a single frame holding the whole log is rejected by its reader)."""
    cctx = zstd.ZstdCompressor()
    return b"".join(cctx.compress(c) for c in chunks)


def _project_key(cwd: str) -> str:
    """DSH projectKey (verified): /\\: -> '-' (runs collapsed), safe chars kept, everything else ~XXXX."""
    readable: list[str] = []
    separator_run = False
    for ch in cwd:
        if ch in "/\\:":
            if not separator_run:
                readable.append("-")
            separator_run = True
        elif ch != "~" and ch in _SAFE:
            readable.append(ch)
            separator_run = False
        else:
            readable.append(f"~{ord(ch):04X}")
            separator_run = False
    out = "".join(readable).lstrip("-") or "root"
    return f"--{out[:251]}--"


def _text_from_content(content) -> str:
    parts = []
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
    return "\n".join(parts)


def _file_from_args(arguments) -> str | None:
    """Extract a file name from tool/call arguments (accepts a JSON string or a parsed dict)."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return None
    if isinstance(arguments, dict):
        for key in ("file_path", "path", "file", "file_name"):
            val = arguments.get(key)
            if isinstance(val, str):
                return val
    return None


class DshAdapter(Adapter):
    agent_id = "dsh"
    display_name = "deepseek-harness"
    install_hint = (
        "install DeepSeek Harness first (npx @deepseek-ai/dsh or the desktop app)"
    )

    def store_path(self) -> str:
        return "~/.dsh/sessions"

    def read_ready(self) -> bool:
        return _root().is_dir()

    def write_ready(self) -> bool:
        """Writing creates the store (mkdir); requires dsh itself to be installed."""
        return _dsh_home().is_dir()

    def store_version(self) -> str:
        return ""  # session format version != product version; do not fake one

    def scan_sessions(self) -> list[SessionMeta]:
        out: list[SessionMeta] = []
        root = _root()
        if not root.is_dir():
            return out
        for proj in sorted(root.iterdir()):
            if not proj.is_dir():
                continue
            for sdir in sorted(proj.iterdir()):
                log = sdir / "session.jsonl.zstd"
                if not log.is_file():
                    continue
                try:
                    meta = self._meta_from_log(log, sdir.name)
                except Exception:
                    continue  # one corrupt session must not break the whole scan (failure isolation)
                if meta:
                    out.append(meta)
        return out

    def _read_events(self, path: Path) -> list[dict]:
        data = _zstd_decompress(path.read_bytes())
        events = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def _meta_from_log(self, path: Path, dir_name: str) -> SessionMeta | None:
        events = self._read_events(path)
        if not events or events[0].get("type") != "session":
            return None
        header = events[0]
        sid = str(header.get("id") or dir_name)
        cwd = header.get("cwd") or None
        title = ""
        turns = 0
        first_user = ""
        for ev in events[1:]:
            t = ev.get("type")
            data = ev.get("data") or {}
            if t == "user/message":
                if (data.get("source") or {}).get("kind") != "tool":
                    turns += 1
                    if not first_user:
                        first_user = " ".join(
                            _text_from_content(data.get("content")).split()
                        )
            elif t == "session/title" and not title:
                v = data.get("title")
                if isinstance(v, str) and v.strip():
                    title = v.strip()
        if not title and first_user:
            title = first_user[:80]
        stat = path.stat()
        return SessionMeta(
            provider_id=self.agent_id,
            session_id=sid,
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
                f"DeepSeek Harness session not found: {sid}", hint="caf list --all"
            )
        events = self._read_events(Path(meta.source_path))
        turns: list[Turn] = []
        for ev in events[1:]:
            t = ev.get("type")
            data = ev.get("data") or {}
            if t == "user/message" and (data.get("source") or {}).get("kind") != "tool":
                text = _text_from_content(data.get("content"))
                if text:
                    turns.append(Turn("user", text))
            elif t == "assistant/message":
                msg = data.get("message") or {}
                text = _text_from_content(msg.get("content"))
                if text:
                    turns.append(Turn("assistant", text))
            elif t == "tool/call" and turns and turns[-1].role == "assistant":
                turns[-1].tools.append(
                    ToolSummary(
                        str(data.get("name", "tool")),
                        "ok",
                        _file_from_args(data.get("arguments")),
                    )
                )
            elif (
                t == "tool/result"
                and turns
                and turns[-1].role == "assistant"
                and data.get("error")
            ):
                if turns[-1].tools:
                    turns[-1].tools[-1].status = "error"
        return SessionIR(meta, turns)

    def resume_command(self, sid: str, project_dir: str | None) -> str:
        prefix = f"cd {shlex.quote(project_dir)} && " if project_dir else ""
        if (_dsh_home() / "profiles" / "tui").is_dir():
            return f"{prefix}dsh --profile tui --resume {sid}"
        # web-only installs (the common dsh setup) have no tui profile: the session
        # shows up in the GUI's session list, so point resume at the web app.
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        return f"{opener} http://127.0.0.1:3080  # dsh web: open the session list and continue ({sid[:8]})"

    def write(self, ir: SessionIR) -> str:
        """Write a native DSH session: header + event sequence, zstd-compressed, atomic write."""
        cwd = ir.session.project_dir or os.getcwd()
        sid = f"session-{uuid4()}"
        now_ms = int(time.time() * 1000)
        events: list[dict] = []
        seq = 0  # dsh requires contiguous seq starting at 0 (events[i].seq === i)
        turn = 0
        first_user_seq: int | None = None
        turn_open = False
        for t in ir.turns:
            if t.role == "user":
                if turn_open:
                    # close the previous turn first (multi-part input / consecutive users)
                    events.append(
                        {
                            "type": "turn/end",
                            "seq": seq,
                            "time": now_ms,
                            "data": {"turn": turn, "reason": {"kind": "completed"}},
                        }
                    )
                    seq += 1
                turn += 1
                turn_open = True
                events.append(
                    {
                        "type": "turn/start",
                        "seq": seq,
                        "time": now_ms,
                        "data": {"turn": turn},
                    }
                )
                seq += 1
                if first_user_seq is None:
                    first_user_seq = seq
                events.append(
                    {
                        "type": "user/message",
                        "seq": seq,
                        "time": now_ms,
                        "surfaceOp": "append",
                        "data": {
                            "id": str(uuid4()),
                            "role": "user",
                            "content": [{"type": "text", "text": t.text}],
                            "source": {"kind": "user"},
                        },
                    }
                )
                seq += 1
            elif t.role == "assistant":
                text = with_tool_lines(t.text, t.tools)
                events.append(
                    {
                        "type": "assistant/message",
                        "seq": seq,
                        "time": now_ms,
                        "surfaceOp": "append",
                        "data": {
                            "turn": turn,
                            "step": 1,
                            "message": {
                                "id": str(uuid4()),
                                "role": "assistant",
                                "content": [{"type": "text", "text": text}]
                                if text
                                else [],
                                "source": {
                                    "kind": "model",
                                    "provider": "caf",
                                    "model": "cross-agent-fork",
                                },
                            },
                        },
                    }
                )
                seq += 1
        if turn_open:
            events.append(
                {
                    "type": "turn/end",
                    "seq": seq,
                    "time": now_ms,
                    "data": {"turn": turn, "reason": {"kind": "completed"}},
                }
            )
            seq += 1

        header = {
            "type": "session",
            "version": 0,
            "id": sid,
            "createdAt": now_ms,
            "cwd": cwd,
            "delegationDepth": 0,
            "agentPreset": "standard",
        }
        lines = [json.dumps(header, ensure_ascii=False)]
        lines += [json.dumps(ev, ensure_ascii=False) for ev in events]

        if ir.session.title and first_user_seq is not None:
            title_ev = {
                "type": "session/title",
                "seq": seq,
                "time": now_ms,
                "data": {
                    "title": ir.session.title[:120],
                    "messageSeqs": [first_user_seq],
                    "source": {"kind": "fallback"},
                },
            }
            lines.append(json.dumps(title_ev, ensure_ascii=False))

        target_dir = _root() / _project_key(cwd) / sid
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "session.jsonl.zstd"
        tmp = path.with_suffix(".tmp")
        frames = [
            (line + "\n").encode("utf-8") for line in lines
        ]  # one frame per JSON line
        tmp.write_bytes(_zstd_compress_frames(frames))
        os.replace(tmp, path)

        if self._meta_from_log(path, sid) is None:
            path.unlink(missing_ok=True)
            raise CafError("DSH write verification failed; rolled back")
        return sid
