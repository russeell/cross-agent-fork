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
from caf.adapters import Adapter
from caf.i18n import t as _t
from caf.core import CafxError, SessionIR, SessionMeta, Turn, atomic_write, read_jsonl


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
)


def _line_has_injection(line: bytes) -> bool:
    """Bytes-level injection detection for counting (markers appear literally in the line)."""
    return any(m in line for m in (
        b"<environment_context>",
        b"# In app browser:",
        b"# Files pasted by the user:",
        b"<recommended_plugins>",
        b"<filesystem",
        b"<permission_profile",
    ))


def _is_injected_text(text: str) -> bool:
    """Text-level injection detection for load_session."""
    t = text.strip().lower()
    return bool(t) and t.startswith(_INJECTED_PREFIXES)


def _first_user_text(files) -> str:
    """First user message of a session (skips injected system blocks), capped at 80 chars."""
    for f in sorted(files):
        for ev in read_jsonl(f):
            p = ev.get("payload") or {}
            if ev.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                text = " ".join(_payload_text(p).split())
                if text and not text.lower().startswith(_POLLUTED_PREFIXES):
                    return text[:80]
    return ""


def _codex_bin() -> Optional[str]:
    """The codex executable: env override (tests/power users) -> PATH."""
    return os.environ.get("CAF_CODEX_BIN") or shutil.which("codex")


def _is_cc_source(path: str) -> bool:
    """The official importer only accepts CC session files under ~/.claude/projects."""
    from caf.adapters.claude import cc_projects_dir
    try:
        return os.path.realpath(path).startswith(os.path.realpath(cc_projects_dir()) + os.sep)
    except Exception:
        return False


def _bridge_cc_mirror(ir: SessionIR) -> str:
    """Non-CC source -> render a CC mirror under projects/__caf_bridge__ (for the official importer, deleted after use)."""
    from caf.adapters.claude import cc_projects_dir, render_cc_lines
    bridge_dir = cc_projects_dir() / "__caf_bridge__"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    sid = str(uuid4())
    path = bridge_dir / f"{sid}.jsonl"
    atomic_write(path, "\n".join(render_cc_lines(ir, sid)) + "\n")
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


def _count_user_turns(path: Path) -> int:
    """Fast user-message count: only inspect the payload head (avoids raw JSON embedded in transcripts)."""
    modern = 0
    legacy = 0
    has_response_item = False
    try:
        with open(path, "rb") as f:
            for line in f:
                if b'"response_item"' in line:
                    has_response_item = True
                    i = line.find(b'"payload"')
                    if i >= 0:
                        head = line[i : i + 300]
                        if b'"type":"message"' in head and b'"role":"user"' in head:
                            if not _line_has_injection(line):
                                modern += 1
                elif b'"type":"user_message"' in line:
                    legacy += 1
    except OSError:
        return 0
    return modern if has_response_item else legacy


def _meta_cwd(path: Path) -> Optional[str]:
    """Read cwd from the session_meta at the top of the file (cheap, first line)."""
    for ev in read_jsonl(path):
        if ev.get("type") == "session_meta":
            p = ev.get("payload") or {}
            return p.get("cwd") or None
    return None


def _session_parent(path: Path) -> Optional[str]:
    """Native lineage: session_meta.parent_thread_id -> "codex:<id>"."""
    for ev in read_jsonl(path):
        if ev.get("type") == "session_meta":
            p = ev.get("payload") or {}
            pid = p.get("parent_thread_id")
            if isinstance(pid, str) and pid:
                return f"codex:{pid}"
            return None
    return None


class CodexAdapter(Adapter):
    agent_id = "codex"
    display_name = "codex"
    install_hint = "npm install -g @openai/codex"

    def detect(self) -> bool:
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
            out = subprocess.run(["codex", "--version"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            return out.split()[0] if out else ""
        except Exception:
            return ""

    def write_ready(self) -> bool:
        return self.detect() and _codex_bin() is not None

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

        def analyze(f: Path):
            sid = _session_id_from_file(f)
            if not sid:
                return None
            return (sid, _meta_cwd(f), _count_user_turns(f),
                    f.stat().st_mtime, _session_parent(f))

        results = [r for r in map(analyze, _rollout_files()) if r]

        groups: dict[str, dict] = {}
        for sid, cwd, turns, mtime, parent in results:
            group = groups.setdefault(sid, {"turns": 0, "mtime": 0.0, "cwd": None, "parent": None})
            group["turns"] += turns
            group["mtime"] = max(group["mtime"], mtime)
            if cwd:
                group["cwd"] = cwd
            if parent:
                group["parent"] = parent

        out: list[SessionMeta] = []
        for sid, group in groups.items():
            info = threads.get(sid, {})
            title = info.get("title") or index.get(sid, "")
            if title and title.strip().lower().startswith(_POLLUTED_PREFIXES):
                # threads-table titles can be polluted by review prompts -> fall back to
                # the first user message (skipping injected blocks)
                files = [f for f in _rollout_files() if _session_id_from_file(f) == sid]
                fallback = _first_user_text(files)
                if fallback:
                    title = fallback
            cwd = info.get("cwd") or group["cwd"]
            updated_ms = info.get("updated_at_ms") or 0
            out.append(SessionMeta(
                provider_id=self.agent_id,
                session_id=sid,
                title=title,
                project_dir=cwd,
                source_path=None,
                turns=group["turns"],
                last_active_at=(updated_ms / 1000) if updated_ms else group["mtime"],
                parent_ref=group["parent"],
            ))
        out.sort(key=lambda m: m.last_active_at, reverse=True)
        return out

    def load_session(self, sid: str) -> SessionIR:
        meta = self.find_session(sid)
        if not meta:
            raise CafxError(_t(f"Codex session not found: {sid}", f"未找到 Codex 会话 {sid}"),
                            hint="caf list --all")
        turns: list[Turn] = []
        seq = 0
        for f in self._files_for_session(meta.session_id):
            for ev in read_jsonl(f):
                msg = _iter_messages(ev)
                if msg:
                    role, text = msg
                    seq += 1
                    turns.append(Turn(seq, role, text))
        return SessionIR(meta, turns)

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

    def write(self, ir: SessionIR) -> str:
        """Official import: externalAgentConfig/import (same mechanism as codex-plugin-cc)."""
        if not _codex_bin():
            raise CafxError(_t("codex CLI not found", "未找到 codex CLI"),
                            hint="npm install -g @openai/codex")
        source = ir.session.source_path
        mirror: Optional[str] = None
        if ir.modified or not (source and Path(source).is_file() and _is_cc_source(source)):
            # IR was sliced/injected, or the source is not CC -> render a CC mirror
            # -> official import (deleted after use)
            mirror = _bridge_cc_mirror(ir)
            source = mirror
        try:
            new_id = import_external_session(source, ir.session.project_dir or os.getcwd())
        finally:
            if mirror:
                try:
                    Path(mirror).unlink(missing_ok=True)
                except OSError:
                    pass
        self.invalidate()
        return new_id


# ---------------------------------------------------------------- official import

IMPORT_COMPLETED = "externalAgentConfig/import/completed"
IMPORT_TIMEOUT_S = 120


def import_external_session(source_path: str, cwd: str, timeout_s: int = IMPORT_TIMEOUT_S) -> str:
    """Start codex app-server (stdio JSON-RPC), run the official import, and wait for completion."""
    bin_path = _codex_bin()
    if not bin_path:
        raise CafxError(_t("codex CLI not found", "未找到 codex CLI"),
                        hint="npm install -g @openai/codex")
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
        rpc.call(1, "initialize", {"clientInfo": {"name": "caf", "version": "0.1.0"}})
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
            ]
        }
        rpc.call(2, "externalAgentConfig/import", params, cancel_on=IMPORT_COMPLETED)
        completed = rpc.wait_for(IMPORT_COMPLETED, timeout_s=timeout_s)
    finally:
        rpc.shutdown()
    return _parse_import_completed(completed)


def _parse_import_completed(params) -> str:
    """Resolve the SESSIONS target (= thread id) from the completed notification's itemTypeResults."""
    if not isinstance(params, dict):
        raise CafxError(_t("Malformed Codex import-completed notification",
                          "Codex 导入完成通知格式异常"), hint="caf doctor")
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
                failure.get("message")
                or failure.get("errorType")
                or _t("unknown error", "未知错误")
            )
            raise CafxError(_t(f"Codex import failed: {message}", f"Codex 导入失败: {message}"),
                            hint=_t("Check the source session format or retry", "检查源会话格式或重试"))
    raise CafxError(_t("Codex import completed but no imported thread found",
                      "Codex 导入完成但未找到 imported thread"), hint="caf doctor")
