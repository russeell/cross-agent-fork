"""caf CLI: fork / list / doctor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from caf import __version__
from caf.adapters import Adapter, discover_adapters, get_adapter
from caf.core import (
    CafError,
    SessionMeta,
    parse_session_ref,
    pick_recent_session,
    slice_turns,
)


def read_adapters() -> list[Adapter]:
    """Adapters that can serve as a fork source (read side available)."""
    return [a for a in discover_adapters() if a.read_ready()]


def _scan(adapter: Adapter) -> list[SessionMeta]:
    """One scan per adapter per command (adapters are re-instantiated per command)."""
    return adapter.scan_cached()


LIST_LIMIT = 20


def _disp_width(text: str) -> int:
    """Display width: CJK and other full-width chars count as 2."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _truncate(text: str, width: int = 34) -> str:
    """Truncate by display width, append '...'."""
    text = " ".join(text.split())
    if _disp_width(text) <= width:
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


def _discovery_line(
    adapters: list[Adapter], sessions: list[SessionMeta] | None = None
) -> str:
    parts = []
    by_agent: dict[str, int] = {}
    if sessions is not None:
        for m in sessions:
            by_agent[m.agent_id] = by_agent.get(m.agent_id, 0) + 1
        adapters = [a for a in adapters if a.agent_id in by_agent]
    for a in adapters:
        try:
            n = by_agent.get(a.agent_id, len(_scan(a)))
        except Exception:
            n = 0
        parts.append(f"{a.display_name or a.agent_id}{f' ({n} sessions)'}")
    if sessions is not None and not parts:
        return "✓ no sessions found"
    head = "✓ found: "
    return head + " + ".join(parts) if parts else "✓ no supported agents found"


def _human_time(ts: float) -> str:
    if not ts:
        return "?"
    delta = datetime.now().timestamp() - ts
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _pad(text: str, width: int) -> str:
    """Right-pad to a display width so columns align."""
    return text + " " * max(0, width - _disp_width(text))


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("", "y", "yes")
    except EOFError:
        return False


def _pick(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except EOFError:
        val = ""
    return val or default


def _stdin_isatty() -> bool:
    """Whether stdin is a terminal (tests can monkeypatch to force interactive mode)."""
    return sys.stdin.isatty()


def _stdout_isatty() -> bool:
    """Whether stdout is a terminal: guidance lines only appear for humans at a TTY;
    agent/pipe/chat consumers get clean data output."""
    return sys.stdout.isatty()


def _render_table(
    rows: list[SessionMeta],
    current_cwd: str,
    show_marker: bool = False,
    numbered: bool = False,
) -> None:
    """Stable-column table: identifiers leftmost, no row numbers (a '1.' prefix would be
    rendered as a Markdown ordered list by chat clients; numbered for interactive pickers)."""
    head = f"  {'#':>2}  " if numbered else "  "
    print(head + f"{_pad('Session', 18)}  {_pad('Title', 28)}{'Turns':>4}  {'Time'}")
    for i, m in enumerate(rows, 1):
        title = _pad(_truncate(m.title, 28) or "(untitled)", 28)
        sid = _pad(f"{m.agent_id}:{m.session_id[:12]}", 18)
        marker = (
            "  <- current project"
            if (
                show_marker
                and m.project_dir
                and os.path.realpath(m.project_dir) == os.path.realpath(current_cwd)
            )
            else ""
        )
        prefix = f"  {i:>2}. " if numbered else "  "
        print(
            f"{prefix}{sid}  {title}{m.turns:>4}  "
            f"{_human_time(m.last_active_at):<9}{marker}"
        )


def _turn_stats(turns) -> tuple[int, int]:
    """(user turns, total items) — 'turns' always means user messages, consistent with list and --at."""
    users = sum(1 for t in turns if t.role == "user")
    return users, len(turns)


def _usable_sessions(adapters: list[Adapter]) -> list[SessionMeta]:
    """Forkable sessions: non-empty and with an existing working directory."""
    out = []
    for meta in _all_sessions(adapters):
        if meta.turns == 0:
            continue
        if not meta.project_dir:
            continue  # unknown cwd would be invented state — never fork it
        if not os.path.isdir(meta.project_dir):
            continue
        out.append(meta)
    return out


def _pick_session(rows: list[SessionMeta], raw: str) -> SessionMeta:
    """Interactive pick: number / id prefix / title keyword; empty = most recent."""
    if not raw:
        return rows[0]
    if raw.isdigit():
        idx = int(raw)
        if not 1 <= idx <= len(rows):
            raise CafError(f"Invalid choice: {raw}", hint=f"Enter 1-{len(rows)}")
        return rows[idx - 1]
    low = raw.lower()
    prefix_matches = [
        m
        for m in rows
        if m.session_id.startswith(low)
        or f"{m.agent_id}:{m.session_id}".startswith(low)
    ]
    if len(prefix_matches) > 1:
        raise CafError(
            f"Prefix {raw} matches {len(prefix_matches)} sessions",
            hint="Use a longer prefix or the full id",
        )
    if prefix_matches:
        return prefix_matches[0]
    for meta in rows:
        if low in meta.title.lower():
            return meta
    raise CafError(f"No session matches: {raw}", hint="caf list --all")


# ---------------------------------------------------------------- fork


def _resolve_source(adapters: list[Adapter], ref: str | None, into: str | None = None):
    """ref -> (adapter, meta); without ref: deterministic — current cwd first,
    then any read-ready agent's most recent; never the target agent."""
    if ref:
        agent_id, sid = parse_session_ref(ref, adapters)
        adapter = get_adapter(adapters, agent_id)
        if sid == "last":
            meta = pick_recent_session(
                [adapter], project_dir=os.getcwd()
            ) or pick_recent_session([adapter])
        else:
            meta = adapter.find_session(sid)
        if not meta:
            raise CafError(
                f"Session not found: {agent_id}:{sid}", hint="caf list --all"
            )
        return adapter, meta

    exclude = (
        get_adapter(adapters, into).agent_id if into else None
    )  # canonical alias (claude -> cc)
    candidates = [a for a in adapters if a.read_ready() and a.agent_id != exclude]
    recent = pick_recent_session(candidates, project_dir=os.getcwd())
    if recent:
        return get_adapter(candidates, recent.agent_id), recent
    recent = pick_recent_session(candidates)
    if recent:
        return get_adapter(candidates, recent.agent_id), recent
    raise CafError("No forkable session found", hint="caf list --all")


def _resolve_target(
    adapters: list[Adapter], source_meta: SessionMeta, into: str | None
) -> Adapter:
    others = [
        a for a in adapters if a.write_ready() and a.agent_id != source_meta.agent_id
    ]
    if into:
        target = get_adapter(adapters, into)
        if not target.write_ready():
            raise CafError(
                f"{into} cannot receive forks (write side unavailable)",
                hint="Run caf doctor for install hints",
            )
        if target.agent_id == source_meta.agent_id:
            raise CafError(
                "Source and target agents must be different",
                hint="Use the agent's native fork for same-agent forks",
            )
        return target
    if len(others) == 1:
        return others[0]
    if not others:
        raise CafError(
            "Only one agent installed; no fork target",
            hint="Install another agent first",
        )
    if not _stdin_isatty():
        raise CafError(
            "Multiple target agents available; pick one with --into",
            hint="--into cc / --into codex / --into dsh",
        )
    print("Choose target agent:")
    for i, a in enumerate(others, 1):
        print(f"  {i}. {a.agent_id}")
    idx = _pick("> target agent: ", "1")
    try:
        n = int(idx)
        if not 1 <= n <= len(others):
            raise IndexError
        return others[n - 1]
    except (ValueError, IndexError):
        raise CafError(f"Invalid choice: {idx}")


def _fork_interactive(adapters: list[Adapter]):
    readable = [a for a in adapters if a.read_ready()]
    print(_discovery_line(readable))
    cwd = os.getcwd()
    usable = sorted(
        _usable_sessions(readable), key=lambda m: m.last_active_at, reverse=True
    )
    real_cwd = os.path.realpath(cwd)
    here = [m for m in usable if os.path.realpath(m.project_dir) == real_cwd]
    others = [m for m in usable if os.path.realpath(m.project_dir) != real_cwd]
    ordered = here + others
    if not ordered:
        raise CafError(
            "No forkable sessions (non-empty with an existing working directory)",
            hint="caf list --all",
        )
    shown = ordered[:LIST_LIMIT]
    _render_table(shown, cwd, show_marker=True, numbered=True)
    if len(shown) < len(ordered):
        print(
            f"  ...and {len(ordered) - LIST_LIMIT} more (search by keyword/longer prefix)"
        )
    raw = _pick("> source [Enter=recent / number / id prefix / title keyword]: ")
    chosen = _pick_session(ordered, raw)
    src_adapter = get_adapter(adapters, chosen.agent_id)
    tgt = _resolve_target(adapters, chosen, None)
    print(
        f"  Fork {chosen.agent_id}:{chosen.session_id[:12]} (whole session) -> {tgt.agent_id}; "
        "original untouched"
    )
    if not _confirm("  [Enter to confirm / q to cancel]: "):
        raise SystemExit(0)
    return src_adapter, chosen, tgt


def _all_sessions(adapters: list[Adapter]) -> list[SessionMeta]:
    out: list[SessionMeta] = []
    for a in adapters:
        try:
            out.extend(_scan(a))
        except Exception as e:
            # one broken agent store must not break the rest
            print(
                f"warning: {a.agent_id} session scan failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
    return out


def cmd_fork(args) -> int:
    adapters = discover_adapters()
    if not any(a.read_ready() or a.write_ready() for a in adapters):
        raise CafError(
            "No supported agents found", hint="Install Claude Code or Codex first"
        )

    if args.ref:
        src_adapter, source_meta = _resolve_source(adapters, args.ref)
        target = _resolve_target(adapters, source_meta, args.into)
    elif _stdin_isatty() and not args.into:
        # interactive picker (Enter = most recent); deterministic rules apply without a TTY
        src_adapter, source_meta, target = _fork_interactive(adapters)
    else:
        src_adapter, source_meta = _resolve_source(adapters, None, into=args.into)
        target = _resolve_target(adapters, source_meta, args.into)

    snapshot = src_adapter.load_session(source_meta.session_id)
    target_name = target.agent_id

    if not snapshot.turns:
        raise CafError(
            "Source session is empty; nothing to fork",
            hint="Pick a session with turns from caf list --all",
        )

    fork_note = ""
    user_turns, total_items = _turn_stats(snapshot.turns)
    if args.at is not None:
        snapshot.turns = slice_turns(snapshot.turns, args.at, snapshot.unfinished_turns)
        snapshot.modified = True
        user_turns, total_items = _turn_stats(snapshot.turns)
        fork_note = f" @{args.at}"

    if not source_meta.project_dir:
        raise CafError(
            "Source session working directory is unknown; it cannot be forked safely.",
            hint="Pick a session with a known cwd from caf list --all",
        )
    if not os.path.isdir(source_meta.project_dir):
        raise CafError(
            f"Source session working directory does not exist: {source_meta.project_dir}",
            hint="Pick another session with caf list --all",
        )

    new_id = target.write(snapshot)

    if not new_id:
        raise CafError("Verify failed: official import returned no thread id")

    resume_cmd = target.resume_command(new_id, source_meta.project_dir)

    if args.json:
        print(
            json.dumps(
                {
                    "source": f"{source_meta.agent_id}:{source_meta.session_id}",
                    "target": target_name,
                    "session_id": new_id,
                    "user_turns": user_turns,
                    "messages": total_items,
                    "resume_command": resume_cmd,
                },
                ensure_ascii=False,
            )
        )
        return 0

    print(
        f"✓ forked  {source_meta.agent_id}:{source_meta.session_id[:8]}{fork_note} "
        f"→ {target_name}:{new_id[:12]}"
    )
    print(f"  resume  {resume_cmd}")
    return 0


# ---------------------------------------------------------------- list


def cmd_list(args) -> int:
    adapters = read_adapters()
    rows = _all_sessions(adapters)
    if args.agent_ref:
        target = get_adapter(adapters, args.agent_ref)
        rows = [m for m in rows if m.agent_id == target.agent_id]
    if args.search:
        kw = args.search.lower()
        rows = [m for m in rows if kw in m.title.lower()]
    hidden_empty = 0
    if not args.all and not args.search:
        hidden_empty = sum(1 for m in rows if m.turns == 0)
        rows = [
            m for m in rows if m.turns > 0
        ]  # empty-session noise filter (same as interactive fork)
    # stable output contract: pure recency sort (the current project is marked, never reordered)
    rows.sort(key=lambda m: m.last_active_at, reverse=True)
    total = len(rows)
    limit = None if args.all else (args.limit if args.limit else LIST_LIMIT)
    shown = rows if limit is None else rows[:limit]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "agentId": m.agent_id,
                        "sessionId": m.session_id,
                        "title": m.title,
                        "projectDir": m.project_dir,
                        "sourcePath": m.source_path,
                        "turns": m.turns,
                        "lastActiveAt": m.last_active_at,
                    }
                    for m in shown
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(_discovery_line(adapters, rows))
    print()
    if shown:
        _render_table(shown, os.getcwd())
        if _stdout_isatty():
            top = shown[0]
            others = [a.agent_id for a in adapters if a.agent_id != top.agent_id]
            into = f" --into {others[0]}" if len(others) == 1 else ""
            print()
            print(
                f"-> fork the most recent: caf fork {top.agent_id}:{top.session_id[:12]}{into}"
            )
            print(
                "  more: --all all | --limit N more | -s search | caf fork interactive"
            )
    if len(shown) < total:
        print(f"  ...{total} sessions, showing {len(shown)}")
    elif hidden_empty:
        print(f"  ...hidden {hidden_empty} empty sessions (--all to view)")
    elif not shown:
        print("  -> try: caf list --all / caf list -s <keyword>")
    return 0


# ---------------------------------------------------------------- doctor


def cmd_doctor(args) -> int:
    discovered = discover_adapters()
    rows = []
    for adapter in discovered:
        read = "ok" if adapter.read_ready() else "off"
        write = "ok" if adapter.write_ready() else "off"
        rows.append(
            {
                "agent": adapter.display_name or adapter.agent_id,
                "from": read,
                "to": write,
                "version": adapter.store_version(),
                "store": adapter.store_path(),
                "install_hint": adapter.install_hint,
            }
        )

    if args.json:
        print(json.dumps({"agents": rows}, ensure_ascii=False, indent=2))
        return 0

    print(_discovery_line([a for a in discovered if a.read_ready()]))
    for r in rows:
        mark = "✓" if r["to"] == "ok" else ("[!]" if r["from"] == "ok" else "[X]")
        print(
            f"  {mark} {r['agent']:8s} from {r['from']:5s} to {r['to']:5s} "
            f"v{r['version'] or '?'}  {r['store']}"
        )
        if (r["to"] == "off" or r["from"] == "off") and r["install_hint"]:
            print(f"      install: {r['install_hint']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caf",
        description="Bring native agent fork across agent boundaries.",
    )
    parser.add_argument("--version", action="version", version=f"caf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fork = sub.add_parser("fork", help="Fork a source session into a target agent")
    p_fork.add_argument(
        "ref",
        nargs="?",
        help="Source session (cc:last / codex:<id>); "
        "defaults to the most recent session in the current directory",
    )
    p_fork.add_argument(
        "--at",
        type=int,
        help="Fork through user turn N (default: the whole current session snapshot)",
    )
    p_fork.add_argument(
        "--into", help="Target agent (default = another installed agent)"
    )
    p_fork.add_argument("--json", action="store_true", help="Machine-friendly output")
    p_fork.set_defaults(func=cmd_fork)

    p_list = sub.add_parser("list", help="Browse sessions across agents")
    p_list.add_argument(
        "agent_ref", nargs="?", help="Only one agent (claude / codex / dsh)"
    )
    p_list.add_argument("-s", "--search", help="Search titles by keyword")
    p_list.add_argument("--limit", type=int, help=f"Max rows (default {LIST_LIMIT})")
    p_list.add_argument(
        "--all", action="store_true", help=f"Show all (default {LIST_LIMIT})"
    )
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_doc = sub.add_parser("doctor", help="Health check and fix suggestions")
    p_doc.add_argument("--json", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return args.func(args)
    except CafError as e:
        print("Error: " + str(e), file=sys.stderr)
        if e.hint:
            print("  -> try: " + e.hint, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except Exception as e:  # safety net: never let the CLI print a naked traceback
        print(f"Unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        print("  -> try: caf doctor", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
