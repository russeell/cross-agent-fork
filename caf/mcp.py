"""Minimal stdio MCP server exposing caf tools (stdlib only, no framework)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from types import SimpleNamespace

from caf import __version__
from caf.cli import cmd_doctor, cmd_fork, cmd_list, cmd_tree

TOOLS = [
    {
        "name": "caf_list",
        "description": "List sessions across installed agents (claude/codex/deepseek-harness). "
                       "Args: agent, search, all, limit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Filter: claude/codex/dsh"},
                "search": {"type": "string", "description": "Title keyword search"},
                "all": {"type": "boolean", "description": "Show all sessions"},
                "limit": {"type": "integer", "description": "Max rows"},
            },
        },
    },
    {
        "name": "caf_fork",
        "description": "Fork a session into another agent (whole session or --at boundary). "
                       "Args: ref, at, through/before, into, dry_run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Source session, e.g. cc:last / codex:<id> / dsh:session-..."},
                "into": {"type": "string", "description": "Target agent: claude/codex/dsh"},
                "at": {"type": "integer", "description": "Fork point (user-message sequence)"},
                "through": {"type": "boolean", "description": "Include turn N (default)"},
                "before": {"type": "boolean", "description": "Strictly before turn N"},
                "dry_run": {"type": "boolean", "description": "Preview only, no write"},
            },
        },
    },
    {
        "name": "caf_tree",
        "description": "Cross-agent lineage tree from native parent fields.",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "caf_doctor",
        "description": "Health check: read/write status, versions, store paths.",
        "inputSchema": {"type": "object"},
    },
]


def _run(cmd, args: dict) -> tuple[str, int]:
    ns = SimpleNamespace(**args)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = cmd(ns)
        return buf.getvalue(), code
    except Exception as e:  # surface errors to the caller instead of crashing the server
        return f"Error: {type(e).__name__}: {e}", 1


def _dispatch(name: str, args: dict) -> tuple[str, int]:
    if name == "caf_list":
        return _run(cmd_list, {
            "agent_ref": args.get("agent"),
            "agent": None, "claude": False, "codex": False,
            "search": args.get("search"),
            "all": args.get("all", False),
            "limit": args.get("limit"),
            "json": False,
        })
    if name == "caf_fork":
        return _run(cmd_fork, {
            "ref": args.get("ref"),
            "into": args.get("into"),
            "at": args.get("at"),
            "through": args.get("through", False),
            "before": args.get("before", False),
            "dry_run": args.get("dry_run", False),
            "copy": False,
            "json": False,
        })
    if name == "caf_tree":
        return _run(cmd_tree, {"json": False})
    if name == "caf_doctor":
        return _run(cmd_doctor, {"json": False})
    return f"Unknown tool: {name}", 1


def serve() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "caf", "version": __version__},
            }})
        elif method in ("initialized", "notifications/initialized"):
            pass
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name", "")
            text, code = _dispatch(name, params.get("arguments") or {})
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": code != 0,
            }})
        elif method == "shutdown":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": None})
            break
    return 0


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()
