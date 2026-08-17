"""caf CLI：fork / list / doctor。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from caf import __version__
from caf.adapters import Adapter, discover_adapters, get_adapter
from caf.i18n import extract_lang, set_lang, t as _t
from caf.core import (
    CafxError,
    SessionMeta,
    disp_width,
    parse_session_ref,
    pick_recent_session,
    slice_turns,
    truncate,
)


def read_adapters() -> list[Adapter]:
    """Adapters that can serve as a fork source (read side available)."""
    return [a for a in discover_adapters() if a.read_ready()]


def _scan(adapter: Adapter) -> list[SessionMeta]:
    """One scan per adapter per command (adapters are re-instantiated per command)."""
    return getattr(adapter, "scan_cached", adapter.scan_sessions)()


LIST_LIMIT = 20  # default visible rows (gh --limit defaults to 30; casr 10; claude/codex pickers ~20)


def _discovery_line(adapters: list[Adapter], sessions: list[SessionMeta] | None = None) -> str:
    parts = []
    by_agent: dict[str, int] = {}
    if sessions is not None:
        for m in sessions:
            by_agent[m.provider_id] = by_agent.get(m.provider_id, 0) + 1
        adapters = [a for a in adapters if a.agent_id in by_agent]
    for a in adapters:
        try:
            n = by_agent.get(a.agent_id, len(_scan(a)))
        except Exception:
            n = 0
        parts.append(f"{a.display_name or a.agent_id}{_t(f' ({n} sessions)', f'（{n} 个会话）')}")
    if sessions is not None and not parts:
        return _t("✓ no sessions found", "✓ 未找到会话")
    head = _t("✓ found: ", "✓ 发现: ")
    return head + " + ".join(parts) if parts else _t("✓ no supported agents found", "✓ 未发现任何受支持的 agent")


def _human_time(ts: float) -> str:
    if not ts:
        return "?"
    delta = datetime.now().timestamp() - ts
    if delta < 60:
        return _t("now", "刚刚")
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _pad(text: str, width: int) -> str:
    """Right-pad to a display width so columns align."""
    return text + " " * max(0, width - disp_width(text))


def _copy(text: str) -> bool:
    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"]):
        try:
            subprocess.run(cmd, input=text, text=True, check=True, timeout=3)
            return True
        except Exception:
            continue
    return False


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


def _render_table(rows: list[SessionMeta], current_cwd: str, show_marker: bool = False,
                  numbered: bool = False) -> None:
    """Stable-column table (gh/kubectl style): identifiers leftmost, no row numbers
    (numbered only for interactive pickers; a '1.' prefix would be rendered as a
    Markdown ordered list by chat clients)."""
    head = f"  {'#':>2}  " if numbered else "  "
    print(head + f"{_pad(_t('Session', '会话'), 18)}  {_pad(_t('Title', '标题'), 28)}"
          f"{_t('Turns', '轮'):>4}  {_t('Time', '时间')}")
    for i, m in enumerate(rows, 1):
        title = _pad(truncate(m.title, 28) or _t("(untitled)", "(无标题)"), 28)
        sid = _pad(f"{m.provider_id}:{m.session_id[:12]}", 18)
        marker = (_t("  <- current project", "  ← 当前项目")
                  if (show_marker and m.project_dir == current_cwd) else "")
        prefix = f"  {i:>2}. " if numbered else "  "
        print(f"{prefix}{sid}  {title}{m.turns:>4}  "
              f"{_human_time(m.last_active_at):<9}{marker}")


def _turn_stats(turns) -> tuple[int, int]:
    """(user turns, total items) — 'turns' always means user messages, consistent with list and --at."""
    users = sum(1 for t in turns if t.role == "user")
    return users, len(turns)


def _turns_label(n: int) -> str:
    return f"{n} user turn" if n == 1 else f"{n} user turns"


def _turns_label_zh(n: int) -> str:
    return f"{n} 个用户轮次"


def _usable_sessions(adapters: list[Adapter]) -> list[SessionMeta]:
    """Forkable sessions: non-empty and with an existing working directory."""
    out = []
    for meta in _all_sessions(adapters):
        if meta.turns == 0:
            continue
        if meta.project_dir and not os.path.isdir(meta.project_dir):
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
            raise CafxError(_t(f"Invalid choice: {raw}", f"无效选择: {raw}"),
                            hint=_t(f"Enter 1-{len(rows)}", f"输入 1-{len(rows)}"))
        return rows[idx - 1]
    low = raw.lower()
    prefix_matches = [m for m in rows if m.session_id.startswith(low)
                      or f"{m.provider_id}:{m.session_id}".startswith(low)]
    if len(prefix_matches) > 1:
        raise CafxError(
            _t(f"Prefix {raw} matches {len(prefix_matches)} sessions",
              f"前缀 {raw} 匹配到 {len(prefix_matches)} 个会话"),
            hint=_t("Use a longer prefix or the full id", "输入更长前缀或完整 id"),
        )
    if prefix_matches:
        return prefix_matches[0]
    for meta in rows:
        if low in meta.title.lower():
            return meta
    raise CafxError(_t(f"No session matches: {raw}", f"未找到匹配的会话: {raw}"), hint="caf list --all")


# ---------------------------------------------------------------- fork


def _resolve_source(adapters: list[Adapter], ref: str | None, into: str | None = None):
    """ref -> (adapter, meta); without ref: deterministic — current cwd first,
    then any read-ready agent's most recent; never the target agent."""
    if ref:
        agent_id, sid = parse_session_ref(ref, adapters)
        adapter = get_adapter(adapters, agent_id)
        if sid == "last":
            meta = pick_recent_session([adapter], project_dir=os.getcwd()) or pick_recent_session([adapter])
        else:
            meta = adapter.find_session(sid)
        if not meta:
            raise CafxError(_t(f"Session not found: {agent_id}:{sid}",
                              f"未找到会话 {agent_id}:{sid}"), hint="caf list --all")
        return adapter, meta

    exclude = get_adapter(adapters, into).agent_id if into else None  # canonical alias (claude -> cc)
    candidates = [a for a in adapters if a.read_ready() and a.agent_id != exclude]
    recent = pick_recent_session(candidates, project_dir=os.getcwd())
    if recent:
        return get_adapter(candidates, recent.provider_id), recent
    recent = pick_recent_session(candidates)
    if recent:
        return get_adapter(candidates, recent.provider_id), recent
    raise CafxError(_t("No forkable session found", "未找到可 fork 的会话"), hint="caf list --all")


def _resolve_target(adapters: list[Adapter], source_meta: SessionMeta, into: str | None) -> Adapter:
    others = [a for a in adapters if a.write_ready() and a.agent_id != source_meta.provider_id]
    if into:
        target = get_adapter(adapters, into)
        if not target.write_ready():
            raise CafxError(
                _t(f"{into} cannot receive forks (write side unavailable)",
                  f"{into} 暂不能接收 fork（写侧不可用）"),
                hint=_t("Run caf doctor for install hints", "运行 caf doctor 查看安装提示"),
            )
        if target.agent_id == source_meta.provider_id:
            raise CafxError(
                _t("Source and target agents must be different",
                  "源和目标 agent 必须不同"),
                hint=_t("Use the agent's native fork for same-agent forks",
                       "同 agent fork 请用该 agent 的原生 fork"),
            )
        return target
    if len(others) == 1:
        return others[0]
    if not others:
        raise CafxError(_t("Only one agent installed; no fork target",
                          "只有一个 agent，无可 fork 目标"),
                        hint=_t("Install another agent first", "安装另一个 agent 后再试"))
    if not _stdin_isatty():
        raise CafxError(
            _t("Multiple target agents available; pick one with --into",
              "存在多个目标 agent，请用 --into 显式指定"),
            hint=_t("--into cc / --into codex / --into dsh", "--into cc / --into codex / --into dsh"),
        )
    print(_t("Choose target agent:", "选择目标 agent："))
    for i, a in enumerate(others, 1):
        print(f"  {i}. {a.agent_id}")
    idx = _pick(_t("> target agent: ", "> 目标 agent: "), "1")
    try:
        n = int(idx)
        if not 1 <= n <= len(others):
            raise IndexError
        return others[n - 1]
    except (ValueError, IndexError):
        raise CafxError(_t(f"Invalid choice: {idx}", f"无效选择: {idx}"))


def _fork_interactive(adapters: list[Adapter]):
    readable = [a for a in adapters if a.read_ready()]
    print(_discovery_line(readable))
    cwd = os.getcwd()
    usable = sorted(_usable_sessions(readable),
                    key=lambda m: m.last_active_at, reverse=True)
    here = [m for m in usable if m.project_dir == cwd]
    others = [m for m in usable if m.project_dir != cwd]
    ordered = here + others
    if not ordered:
        raise CafxError(_t("No forkable sessions (non-empty with an existing working directory)",
                          "没有可 fork 的会话（非空且工作目录存在）"),
                        hint="caf list --all")
    shown = ordered[:LIST_LIMIT]
    _render_table(shown, cwd, show_marker=True, numbered=True)
    if len(shown) < len(ordered):
        print(_t(f"  ...and {len(ordered) - LIST_LIMIT} more (search by keyword/longer prefix)",
                f"  …还有 {len(ordered) - LIST_LIMIT} 个（输入关键词/更长前缀可搜索到）"))
    raw = _pick(_t("> source [Enter=recent / number / id prefix / title keyword]: ",
                  "> 源会话 [回车=最近 / 编号 / id 前缀 / 标题关键词]: "))
    chosen = _pick_session(ordered, raw)
    src_adapter = get_adapter(adapters, chosen.provider_id)
    tgt = _resolve_target(adapters, chosen, None)
    print(_t(f"  Fork {chosen.provider_id}:{chosen.session_id[:12]} (whole session) -> {tgt.agent_id}; "
            "original untouched",
            f"  将 fork {chosen.provider_id}:{chosen.session_id[:12]} 整会话 → {tgt.agent_id}（原会话不动）"))
    if not _confirm(_t("  [Enter to confirm / q to cancel]: ", "  [回车确认 / q 取消]: ")):
        raise SystemExit(0)
    return src_adapter, chosen, tgt


def _all_sessions(adapters: list[Adapter]) -> list[SessionMeta]:
    out: list[SessionMeta] = []
    for a in adapters:
        try:
            out.extend(_scan(a))
        except Exception as e:
            # failure isolation (cc-switch §8.2): one broken agent store must not break the rest
            print(_t(f"warning: {a.agent_id} session scan failed: {type(e).__name__}: {e}",
                    f"⚠ {a.agent_id} 会话扫描失败: {type(e).__name__}: {e}"),
                  file=sys.stderr)
    return out


def cmd_fork(args) -> int:
    adapters = discover_adapters()
    if not any(a.read_ready() or a.write_ready() for a in adapters):
        raise CafxError(_t("No supported agents found", "未发现任何受支持的 agent"),
                        hint=_t("Install Claude Code or Codex first", "安装 Claude Code 或 Codex 后再试"))

    if args.ref:
        src_adapter, source_meta = _resolve_source(adapters, args.ref)
        target = _resolve_target(adapters, source_meta, args.into)
    elif _stdin_isatty() and not args.into:
        # interactive picker (Enter = most recent); deterministic rules apply without a TTY
        src_adapter, source_meta, target = _fork_interactive(adapters)
    else:
        src_adapter, source_meta = _resolve_source(adapters, None, into=args.into)
        target = _resolve_target(adapters, source_meta, args.into)

    ir = src_adapter.load_session(source_meta.session_id)
    target_name = target.agent_id

    fork_note = ""
    user_turns, total_items = _turn_stats(ir.turns)
    if args.at is not None:
        boundary = "before" if args.before else "through"
        ir.turns, warning = slice_turns(ir.turns, args.at, boundary)
        ir.modified = True
        user_turns, total_items = _turn_stats(ir.turns)
        if warning:
            print(f"⚠ {warning}")
        if not ir.turns:
            raise CafxError(_t("Nothing to fork", "没有可 fork 的轮次"))
        fork_note = f" @{args.at}"

    if source_meta.project_dir and not os.path.isdir(source_meta.project_dir):
        raise CafxError(
            _t(f"Source session working directory does not exist: {source_meta.project_dir}",
              f"源会话的工作目录不存在: {source_meta.project_dir}"),
            hint=_t("Pick another session with caf list --all", "caf list --all 选择其他会话"),
        )

    if args.dry_run:
        print(_t(f"Preview: {source_meta.provider_id}:{source_meta.session_id[:8]} -> {target_name} "
                f"({_turns_label(user_turns)} / {total_items} messages, original untouched)",
                f"✓ 预览: {source_meta.provider_id}:{source_meta.session_id[:8]} → {target_name}"
                f"（{_turns_label_zh(user_turns)} / {total_items} 条消息，原会话不动）"))
        print()
        print(_t("-> resume: ", "→ 继续: ") + target.resume_command('<new-id>', source_meta.project_dir))
        return 0

    new_id = target.write(ir)

    # verify: adapters self-verify and roll back on failure (claude/dsh);
    # codex import success is the thread identity itself
    if not new_id:
            raise CafxError(_t("Verify failed: official import returned no thread id",
                              "校验失败：官方导入未返回线程 id"))

    resume_cmd = target.resume_command(new_id, source_meta.project_dir)
    undo_cmd = target.undo_command(new_id, source_meta.project_dir) if hasattr(target, "undo_command") else ""

    if args.json:
        print(json.dumps({
            "source": f"{source_meta.provider_id}:{source_meta.session_id}",
            "target": target_name,
            "session_id": new_id,
            "turns": len(ir.turns),
            "resume_command": resume_cmd,
        }, ensure_ascii=False))
        return 0

    write_desc = _t("official import", "官方导入") if target_name == "codex" else _t("file-level envelope", "文件级信封")
    print(_t(f"Forked: {source_meta.provider_id}:{source_meta.session_id[:8]}{fork_note} -> {target_name} "
            f"({_turns_label(user_turns)} / {total_items} messages, original untouched)",
            f"✓ 分叉: {source_meta.provider_id}:{source_meta.session_id[:8]}{fork_note} → {target_name}"
            f"（{_turns_label_zh(user_turns)} / {total_items} 条消息，原会话不动）"))
    print(_t(f"Written: {target_name} {new_id[:8]}... ({write_desc})",
            f"✓ 写入: {target_name} {new_id[:8]}...（{write_desc}）"))
    print()
    print(_t("-> resume: ", "→ 继续: ") + resume_cmd + (_t("     [-c copy]", "     [-c 复制]") if args.copy else ""))
    if undo_cmd:
        print(_t(f"Undo: {undo_cmd}", f"撤销: {undo_cmd}"))
    if args.copy and _copy(resume_cmd):
        print(_t("Copied to clipboard", "✓ 已复制到剪贴板"))
    return 0


# ---------------------------------------------------------------- list

def cmd_list(args) -> int:
    adapters = read_adapters()
    rows = _all_sessions(adapters)
    agent = args.agent or args.agent_ref or (
        "claude" if args.claude else ("codex" if args.codex else None)
    )
    if agent:
        target = get_adapter(adapters, agent)
        rows = [m for m in rows if m.provider_id == target.agent_id]
    if args.search:
        kw = args.search.lower()
        rows = [m for m in rows if kw in m.title.lower()]
    hidden_empty = 0
    if not args.all and not args.search:
        hidden_empty = sum(1 for m in rows if m.turns == 0)
        rows = [m for m in rows if m.turns > 0]  # empty-session noise filter (same as interactive fork)
    # stable output contract: pure recency sort (the current project is marked, never reordered)
    rows.sort(key=lambda m: m.last_active_at, reverse=True)
    total = len(rows)
    limit = None if args.all else (args.limit if args.limit else LIST_LIMIT)
    shown = rows if limit is None else rows[:limit]

    if args.json:
        print(json.dumps([
            {"providerId": m.provider_id, "sessionId": m.session_id, "title": m.title,
             "projectDir": m.project_dir, "sourcePath": m.source_path, "turns": m.turns,
             "lastActiveAt": m.last_active_at}
            for m in shown
        ], ensure_ascii=False, indent=2))
        return 0

    print(_discovery_line(adapters, rows))
    print()
    if shown:
        _render_table(shown, os.getcwd())
        if _stdout_isatty():
            top = shown[0]
            others = [a.agent_id for a in adapters if a.agent_id != top.provider_id]
            into = f" --into {others[0]}" if len(others) == 1 else ""
            print()
            print(_t(f"-> fork the most recent: caf fork {top.provider_id}:{top.session_id[:12]}{into}",
                     f"→ fork 最近的: caf fork {top.provider_id}:{top.session_id[:12]}{into}"))
            print(_t("  more: --all all | --limit N more | -s search | caf fork interactive",
                     "  更多: --all 全部 | --limit N 更多 | -s 搜索 | caf fork 交互选择"))
    if len(shown) < total:
        print(_t(f"  ...{total} sessions, showing {len(shown)}",
                f"  …共 {total} 个，仅显示 {len(shown)} 个"))
    elif hidden_empty:
        print(_t(f"  ...hidden {hidden_empty} empty sessions (--all to view)",
                f"  …已隐藏 {hidden_empty} 个空会话（--all 查看）"))
    elif not shown:
        print(_t("  -> try: caf list --all / caf list -s <keyword>",
                "  → 试试: caf list --all / caf list -s 关键词"))
    return 0


# ---------------------------------------------------------------- doctor


def cmd_doctor(args) -> int:
    discovered = discover_adapters()
    rows = []
    for adapter in discovered:
        installed = adapter.detect()
        read = "ok" if installed else "off"
        write = "ok" if adapter.write_ready() else ("planned" if installed else "off")
        rows.append({
            "agent": adapter.display_name or adapter.agent_id,
            "read": read,
            "write": write,
            "version": adapter.store_version(),
            "store": adapter.store_path(),
            "install_hint": adapter.install_hint,
        })

    if args.json:
        print(json.dumps({"agents": rows}, ensure_ascii=False, indent=2))
        return 0

    print(_discovery_line([a for a in discovered if a.detect()]))
    print(_t("Legend: ✅ ready  [!] partial  [X] not installed",
            "图例：✅ 可用  [!] 部分能力  [X] 未安装"))
    for r in rows:
        mark = "✅" if r["write"] == "ok" else ("[!]" if r["read"] == "ok" else "[X]")
        print(f"  {mark} {r['agent']:8s} read {r['read']:6s} write {r['write']:6s} "
              f"v{r['version'] or '?'}  {r['store']}")
        if r["write"] == "off" and r["install_hint"]:
            print(_t(f"      install: {r['install_hint']}", f"      安装: {r['install_hint']}"))
    return 0


# ---------------------------------------------------------------- tree


def cmd_tree(args) -> int:
    """Cross-agent lineage tree: default shows only cross-agent edges (--all shows full lineage)."""
    from caf.tree import build_lineage, render, session_key

    metas = sorted(_all_sessions(discover_adapters()), key=lambda m: m.last_active_at, reverse=True)
    show_all = getattr(args, "all", False)
    roots, children, edges = build_lineage(metas, show_all)

    if args.json:
        print(json.dumps({
            "sessions": [session_key(m) for m in metas],
            "roots": [session_key(m) for m in roots],
            "edges": edges,
        }, ensure_ascii=False, indent=2))
        return 0

    render(metas, roots, children, edges, show_all)
    return 0


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caf",
        description="Cross-agent session fork: whole session + cwd + resumable identity, "
                    "original untouched",
    )
    parser.add_argument("--version", action="version", version=f"caf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fork = sub.add_parser("fork", help="Fork a source session into a target agent")
    p_fork.add_argument("ref", nargs="?", help="Source session (cc:last / codex:<id>); "
                                               "defaults to the most recent session in the current directory")
    p_fork.add_argument("--at", type=int, help="Fork point: user-message sequence "
                                               "(default = last completed turn)")
    bound = p_fork.add_mutually_exclusive_group()
    bound.add_argument("--through", action="store_true", help="Include turn N (default)")
    bound.add_argument("--before", action="store_true", help="Strictly before turn N")
    p_fork.add_argument("--into", help="Target agent (default = another installed agent)")
    p_fork.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    p_fork.add_argument("-c", "--copy", action="store_true", help="Copy the resume command")
    p_fork.add_argument("--json", action="store_true", help="Machine-friendly output")
    p_fork.set_defaults(func=cmd_fork)

    p_list = sub.add_parser("list", help="Browse sessions across agents")
    p_list.add_argument("agent_ref", nargs="?",
                        help="Only one agent (claude / codex / cc; same as --agent)")
    p_list.add_argument("--agent", help="Only one agent")
    p_list.add_argument("--claude", action="store_true",
                        help="Only Claude Code sessions (same as --agent claude)")
    p_list.add_argument("--codex", action="store_true",
                        help="Only Codex sessions (same as --agent codex)")
    p_list.add_argument("-s", "--search", help="Search titles by keyword")
    p_list.add_argument("--limit", type=int, help=f"Max rows (default {LIST_LIMIT})")
    p_list.add_argument("--all", action="store_true", help=f"Show all (default {LIST_LIMIT})")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_doc = sub.add_parser("doctor", help="Health check and fix suggestions")
    p_doc.add_argument("--json", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_tree = sub.add_parser("tree", help="Cross-agent lineage tree")
    p_tree.add_argument("--all", action="store_true", help="Show all edges (including same-agent)")
    p_tree.add_argument("--json", action="store_true")
    p_tree.set_defaults(func=cmd_tree)

    sub.add_parser("mcp", help="stdio MCP server (desktop/chat clients)").set_defaults(func=cmd_mcp)
    return parser


def cmd_mcp(args) -> int:
    from caf.mcp import serve
    return serve()


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    argv, lang = extract_lang(raw)
    set_lang(lang if lang else detect_lang_env())
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CafxError as e:
        print(_t("Error: ", "✗ ") + str(e))
        if e.hint:
            print(_t("  -> try: ", "  → 试试: ") + e.hint)
        return 1
    except KeyboardInterrupt:
        print("")
        return 130
    except Exception as e:  # safety net: never let the CLI print a naked traceback
        print(_t(f"Unexpected error: {type(e).__name__}: {e}",
                f"✗ 意外错误: {type(e).__name__}: {e}"))
        print(_t("  -> try: caf doctor", "  → 试试: caf doctor"))
        return 1


if __name__ == "__main__":
    sys.exit(main())


def detect_lang_env() -> str:
    from caf.i18n import detect_lang
    return detect_lang()
