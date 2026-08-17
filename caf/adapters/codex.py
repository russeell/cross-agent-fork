"""Codex adapter: read rollouts (tiered fallback) + official external-agent import."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional
from uuid import uuid4

from caf._rpc import RpcClient
from caf import __version__
from caf.adapters import Adapter
from caf.core import (
    CafError,
    ForkSnapshot,
    SessionMeta,
    Turn,
    append_evidence,
    atomic_write,
    read_jsonl,
    tool_call_text,
    tool_result_text,
)


def _codex_home() -> Path:
    return Path(os.environ.get("CAF_CODEX_HOME", str(Path.home() / ".codex")))


_POLLUTED_PREFIXES = (
    "the following is the codex agent history",
    "<environment_context>",
    "<recommended_plugins>",
    "# files pasted by the user:",
    "<filesystem",
    "<permission_profile",
)

_INJECTED_PREFIXES = (
    "<environment_context>",
    "# in app browser:",
    "# files pasted by the user:",
    "<recommended_plugins>",
    "<filesystem",
    "<permission_profile",
    "<turn_aborted>",
)


def _line_has_injection(line: bytes) -> bool:
    """Bytes-level injection detection for counting (markers appear literally in the line)."""
    return any(
        m in line
        for m in (
            b"<environment_context>",
            b"# In app browser:",
            b"# Files pasted by the user:",
            b"<recommended_plugins>",
            b"<filesystem",
            b"<permission_profile",
        )
    )


def _is_injected_text(text: str) -> bool:
    """Text-level injection detection for load_session."""
    t = text.strip().lower()
    return bool(t) and t.startswith(_INJECTED_PREFIXES)


def _codex_bin() -> Optional[str]:
    """The codex executable: env override (tests/power users) -> PATH."""
    return os.environ.get("CAF_CODEX_BIN") or shutil.which("codex")


def _is_cc_source(path: str) -> bool:
    """The official importer only accepts CC session files under ~/.claude/projects."""
    from caf.adapters.claude import cc_projects_dir

    try:
        return os.path.realpath(path).startswith(
            os.path.realpath(cc_projects_dir()) + os.sep
        )
    except Exception:
        return False


def _bridge_cc_mirror(snapshot: ForkSnapshot) -> str:
    """Non-CC source -> render a CC mirror under projects/__caf_bridge__ (for the official importer, deleted after use)."""
    from caf.adapters.claude import cc_projects_dir, render_cc_lines

    bridge_dir = cc_projects_dir() / "__caf_bridge__"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    sid = str(uuid4())
    path = bridge_dir / f"{sid}.jsonl"
    atomic_write(path, "\n".join(render_cc_lines(snapshot, sid)) + "\n")
    return str(path)


def _sessions_dir() -> Path:
    return _codex_home() / "sessions"


def _rollout_files():
    root = _sessions_dir()
    if not root.is_dir():
        return
    for y in sorted(root.iterdir()):
        if not y.is_dir():
            continue
        for m in sorted(y.iterdir()):
            if not m.is_dir():
                continue
            for d in sorted(m.iterdir()):
                if not d.is_dir():
                    continue
                for f in sorted(d.glob("rollout-*.jsonl")):
                    yield f


def _payload_text(payload: dict) -> str:
    """Extract text from a response_item payload (new content[] / legacy text)."""
    content = payload.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


def _iter_messages(ev: dict) -> Optional[tuple[str, str]]:
    """Yield (role, text) from one event: modern response_item or legacy *_message."""
    t = ev.get("type")
    p = ev.get("payload") or {}
    if t == "response_item" and p.get("type") == "message":
        role = p.get("role")
        if role in ("user", "assistant"):
            text = _payload_text(p)
            if role == "user" and _is_injected_text(text):
                return None  # skip system-injected user messages (environment context, browser state, ...)
            return (role, text) if text else None
    elif t in ("user_message", "assistant_message"):
        text = _payload_text(p)
        return ("user" if t == "user_message" else "assistant", text) if text else None
    return None


def _iter_tool_events(ev: dict) -> tuple[str, dict] | None:
    """(call|output, payload) from one event: modern response_item or legacy events."""
    t = ev.get("type")
    p = ev.get("payload") or {}
    if t == "response_item" and p.get("type") == "function_call":
        return "call", {
            "name": str(p.get("name", "tool")),
            "call_id": str(p.get("call_id", "")),
            "arguments": str(p.get("arguments", "") or ""),
        }
    if t == "response_item" and p.get("type") == "function_call_output":
        return "output", {
            "call_id": str(p.get("call_id", "")),
            "output": _payload_text(p) or str(p.get("output", "") or ""),
            "is_error": bool(p.get("is_error")),
        }
    if t == "function_call":
        return "call", {
            "name": str(p.get("name", "tool")),
            "call_id": str(p.get("call_id", "")),
            "arguments": str(p.get("arguments", "") or ""),
        }
    if t == "function_call_output":
        return "output", {
            "call_id": str(p.get("call_id", "")),
            "output": _payload_text(p) or str(p.get("output", "") or ""),
            "is_error": bool(p.get("is_error")),
        }
    return None


def _threads_index(codex_home: Path) -> dict:
    """Index of the threads sqlite table: id -> {title, cwd, updated_at_ms, has_user_event}."""
    db = codex_home / "state_5.sqlite"
    out: dict = {}
    if not db.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT id, title, cwd, updated_at_ms, has_user_event "
                "FROM threads WHERE archived = 0"
            )
            for tid, title, cwd, updated_ms, has_user in rows:
                out[str(tid)] = {
                    "title": title or "",
                    "cwd": cwd or None,
                    "updated_at_ms": updated_ms or 0,
                    "has_user_event": bool(has_user),
                }
        finally:
            con.close()
    except Exception:
        pass
    return out


def _session_id_from_file(path: Path) -> Optional[str]:
    """Extract the session id from the rollout session_meta (falls back to the file name)."""
    for ev in read_jsonl(path):
        if ev.get("type") == "session_meta":
            p = ev.get("payload") or {}
            return p.get("id") or p.get("session_id") or None
    return None


_MAX_TEXT_LINE = (
    256 * 1024
)  # skip first-user-text extraction for huge lines (attachments/base64)


def _user_text_from_line(line: bytes) -> str:
    """First non-polluted user text from one rollout line (title fallback), capped at 80 chars."""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return ""
    p = ev.get("payload") or {}
    if (
        ev.get("type") != "response_item"
        or p.get("type") != "message"
        or p.get("role") != "user"
    ):
        return ""
    text = " ".join(_payload_text(p).split())
    if not text or text.lower().startswith(_POLLUTED_PREFIXES):
        return ""
    return text[:80]


def _analyze_rollout(path: Path) -> Optional[dict]:
    """One pass over a rollout: id / cwd / user turns / first user text / mtime."""
    sid = cwd = None
    first_text = ""
    modern = legacy = 0
    has_response_item = False
    try:
        with open(path, "rb") as f:
            for line in f:
                if b'"session_meta"' in line and (sid is None or cwd is None):
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        ev = None
                    if ev:
                        p = ev.get("payload") or {}
                        if sid is None:
                            sid = p.get("id") or p.get("session_id") or None
                        if cwd is None:
                            cwd = p.get("cwd") or None
                if b'"response_item"' in line:
                    has_response_item = True
                    i = line.find(b'"payload"')
                    if i >= 0:
                        head = line[i : i + 300]
                        if b'"type":"message"' in head and b'"role":"user"' in head:
                            if not _line_has_injection(line):
                                modern += 1
                                if not first_text and len(line) < _MAX_TEXT_LINE:
                                    first_text = _user_text_from_line(line)
                elif b'"type":"user_message"' in line:
                    legacy += 1
    except OSError:
        return None
    if not sid:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return {
        "sid": sid,
        "cwd": cwd,
        "turns": modern if has_response_item else legacy,
        "first_user_text": first_text,
        "mtime": mtime,
    }


class CodexAdapter(Adapter):
    agent_id = "codex"
    display_name = "codex"
    install_hint = "npm install -g @openai/codex"

    def read_ready(self) -> bool:
        return _sessions_dir().is_dir()

    def store_version(self) -> str:
        """CLI version: version.json latest_version, falling back to the CLI output."""
        vf = _codex_home() / "version.json"
        try:
            v = json.loads(vf.read_text(encoding="utf-8")).get("latest_version", "")
            if v:
                return v
        except Exception:
            pass
        try:
            out = subprocess.run(
                ["codex", "--version"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            return out.split()[-1] if out else ""  # "codex-cli 0.144.0" -> "0.144.0"
        except Exception:
            return ""

    def write_ready(self) -> bool:
        return _codex_bin() is not None

    def store_path(self) -> str:
        return "~/.codex"

    def _load_index(self) -> dict:
        idx = _codex_home() / "session_index.jsonl"
        out: dict = {}
        if idx.is_file():
            for ev in read_jsonl(idx):
                if isinstance(ev, dict) and ev.get("id") and ev.get("thread_name"):
                    out[str(ev["id"])] = str(ev["thread_name"])
        return out

    def scan_sessions(self) -> list[SessionMeta]:
        threads = _threads_index(_codex_home())
        index = self._load_index()

        groups: dict[str, dict] = {}
        for f in _rollout_files():
            info = _analyze_rollout(f)
            if not info:
                continue
            group = groups.setdefault(
                info["sid"], {"turns": 0, "mtime": 0.0, "cwd": None, "first": ""}
            )
            group["turns"] += info["turns"]
            group["mtime"] = max(group["mtime"], info["mtime"])
            if info["cwd"]:
                group["cwd"] = info["cwd"]
            if not group["first"]:
                group["first"] = info["first_user_text"]

        out: list[SessionMeta] = []
        for sid, group in groups.items():
            info = threads.get(sid, {})
            title = info.get("title") or index.get(sid, "")
            if title and title.strip().lower().startswith(_POLLUTED_PREFIXES):
                # threads-table titles can be polluted by review prompts -> fall back to
                # the first user message (skipping injected blocks)
                fallback = group["first"]
                if fallback:
                    title = fallback
            cwd = info.get("cwd") or group["cwd"]
            updated_ms = info.get("updated_at_ms") or 0
            out.append(
                SessionMeta(
                    provider_id=self.agent_id,
                    session_id=sid,
                    title=title,
                    project_dir=cwd,
                    source_path=None,
                    turns=group["turns"],
                    last_active_at=(updated_ms / 1000)
                    if updated_ms
                    else group["mtime"],
                )
            )
        out.sort(key=lambda m: m.last_active_at, reverse=True)
        return out

    def load_session(self, sid: str) -> ForkSnapshot:
        meta = self.find_session(sid)
        if not meta:
            raise CafError(f"Codex session not found: {sid}", hint="caf list --all")
        turns: list[Turn] = []
        pending: dict[str, tuple[int, str]] = {}
        user_turn = 0
        active_task: str | None = None
        task_turns: dict[str, int] = {}
        unfinished: set[int] = set()
        for f in self._files_for_session(meta.session_id):
            for ev in read_jsonl(f):
                payload = ev.get("payload") or {}
                if ev.get("type") == "event_msg":
                    event_type = payload.get("type")
                    if event_type == "task_started":
                        active_task = str(payload.get("turn_id", "")) or None
                    elif event_type in ("task_complete", "turn_aborted"):
                        task_id = str(payload.get("turn_id", ""))
                        ordinal = task_turns.get(task_id)
                        if event_type == "turn_aborted" and ordinal:
                            unfinished.add(ordinal)
                        if task_id == active_task:
                            active_task = None
                msg = _iter_messages(ev)
                if msg:
                    role, text = msg
                    if role == "user":
                        user_turn += 1
                        if active_task:
                            task_turns[active_task] = user_turn
                    if (
                        role == "assistant"
                        and turns
                        and turns[-1].role == "assistant"
                        and any(idx == len(turns) - 1 for idx, _ in pending.values())
                    ):
                        # Some Codex rollouts emit function_call before the textual
                        # assistant item. Keep both in the same portable turn.
                        turns[-1].text = append_evidence(turns[-1].text, text)
                    else:
                        turns.append(Turn(role, text))
                    continue
                tool = _iter_tool_events(ev)
                if not tool:
                    continue
                kind, data = tool
                if kind == "call":
                    if not turns or turns[-1].role != "assistant":
                        turns.append(Turn("assistant", ""))
                    turns[-1].text = append_evidence(
                        turns[-1].text,
                        tool_call_text(data["name"], data["arguments"]),
                    )
                    if data["call_id"]:
                        pending[data["call_id"]] = (len(turns) - 1, data["name"])
                else:
                    match = pending.get(data["call_id"])
                    if not match:
                        if not turns or turns[-1].role != "assistant":
                            turns.append(Turn("assistant", ""))
                        idx, name = len(turns) - 1, "tool"
                    else:
                        idx, name = match
                    turns[idx].text = append_evidence(
                        turns[idx].text,
                        tool_result_text(name, data["output"], data["is_error"]),
                    )
        if active_task and active_task in task_turns:
            unfinished.add(task_turns[active_task])
        return ForkSnapshot(meta, turns, unfinished_turns=unfinished)

    def _files_for_session(self, sid: str) -> list[Path]:
        """All rollout files for a session id (paged threads merged in path order)."""
        files = [f for f in _rollout_files() if _session_id_from_file(f) == sid]
        if not files:
            # fallback: match by file-name prefix (legacy format)
            files = [f for f in _rollout_files() if sid in f.name]
        return sorted(files)

    def resume_command(self, sid: str, project_dir: Optional[str]) -> str:
        prefix = f"cd {shlex.quote(project_dir)} && " if project_dir else ""
        return f"{prefix}codex resume {sid}"

    def write(self, snapshot: ForkSnapshot) -> str:
        """Official import: externalAgentConfig/import (same mechanism as codex-plugin-cc)."""
        if not _codex_bin():
            raise CafError("codex CLI not found", hint="npm install -g @openai/codex")
        source = snapshot.session.source_path
        mirror: Optional[str] = None
        if snapshot.modified or not (
            source and Path(source).is_file() and _is_cc_source(source)
        ):
            # IR was sliced/injected, or the source is not CC -> render a CC mirror
            # -> official import (deleted after use)
            mirror = _bridge_cc_mirror(snapshot)
            source = mirror
        try:
            cwd = snapshot.session.project_dir
            if not cwd or not os.path.isdir(cwd):
                raise CafError(
                    "Cannot fork: source working directory is unknown or does not exist."
                )
            new_id = import_external_session(source, cwd)
        finally:
            if mirror:
                try:
                    Path(mirror).unlink(missing_ok=True)
                except OSError:
                    pass
        return new_id


# ---------------------------------------------------------------- official import

IMPORT_COMPLETED = "externalAgentConfig/import/completed"
IMPORT_TIMEOUT_S = 120


def import_external_session(
    source_path: str, cwd: str, timeout_s: int = IMPORT_TIMEOUT_S
) -> str:
    """Start codex app-server (stdio JSON-RPC), run the official import, and wait for completion."""
    bin_path = _codex_bin()
    if not bin_path:
        raise CafError("codex CLI not found", hint="npm install -g @openai/codex")
    proc = subprocess.Popen(
        [bin_path, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    rpc = RpcClient(proc)
    try:
        rpc.call(
            1, "initialize", {"clientInfo": {"name": "caf", "version": __version__}}
        )
        rpc.notify("initialized")
        params = {
            "source": "caf",
            "migrationItems": [
                {
                    "itemType": "SESSIONS",
                    "description": f"caf fork: {Path(source_path).name}",
                    "cwd": None,
                    "details": {
                        "plugins": [],
                        "skills": [],
                        "sessions": [{"path": source_path, "cwd": cwd, "title": None}],
                        "mcpServers": [],
                        "hooks": [],
                        "subagents": [],
                        "commands": [],
                    },
                }
            ],
        }
        rpc.call(2, "externalAgentConfig/import", params, cancel_on=IMPORT_COMPLETED)
        completed = rpc.wait_for(IMPORT_COMPLETED, timeout_s=timeout_s)
    finally:
        rpc.shutdown()
    return _parse_import_completed(completed)


def _parse_import_completed(params) -> str:
    """Resolve the SESSIONS target (= thread id) from the completed notification's itemTypeResults."""
    if not isinstance(params, dict):
        raise CafError(
            "Malformed Codex import-completed notification", hint="caf doctor"
        )
    results = params.get("itemTypeResults") or []
    for result in results:
        if not isinstance(result, dict) or result.get("itemType") != "SESSIONS":
            continue
        successes = result.get("successes") or []
        failures = result.get("failures") or []
        if successes:
            target = successes[0].get("target")
            if isinstance(target, str) and target:
                return target
        if failures:
            failure = failures[0]
            message = (
                failure.get("message") or failure.get("errorType") or "unknown error"
            )
            raise CafError(
                f"Codex import failed: {message}",
                hint="Check the source session format or retry",
            )
    raise CafError(
        "Codex import completed but no imported thread found", hint="caf doctor"
    )
