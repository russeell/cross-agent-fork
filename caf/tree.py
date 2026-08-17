"""Cross-agent lineage tree: build + render (caf tree), pure logic + printing."""

from __future__ import annotations

from caf.core import SessionMeta, truncate
from caf.i18n import t as _t


def session_key(meta: SessionMeta) -> str:
    return f"{meta.provider_id}:{meta.session_id}"


def build_lineage(metas: list[SessionMeta], show_all: bool = False):
    """Split sessions into (roots, children, edges); same-agent edges hidden unless show_all."""
    index = {session_key(m): m for m in metas}
    children: dict[str, list] = {}
    roots: list[SessionMeta] = []
    edges: list[dict] = []
    for m in metas:
        parent = None
        cross = False
        if m.parent_ref:
            if m.parent_ref in index:
                parent = m.parent_ref
            else:
                for key in index:  # prefix fallback (rare)
                    if key.startswith(m.parent_ref):
                        parent = key
                        break
            if parent:
                cross = session_key(m).split(":", 1)[0] != parent.split(":", 1)[0]
        if parent is None:
            roots.append(m)
        else:
            if show_all or cross:
                children.setdefault(parent, []).append(m)
            else:
                roots.append(m)  # same-agent edge hidden by default
            edges.append({"child": session_key(m), "parent": parent, "cross": cross})
    return roots, children, edges


def render(metas: list[SessionMeta], roots, children, edges, show_all: bool = False) -> None:
    """Print the tree: summary line + one branch per root."""
    shown = _t(" (all)", "（全部）") if show_all else _t(
        " (cross-agent edges only, --all for all)", "（仅跨 agent 边，--all 显示全部）")
    shown_edges = len(edges) if show_all else sum(1 for e in edges if e["cross"])
    print(_t(f"Cross-agent lineage tree{shown}: {len(roots)} roots, "
            f"{shown_edges} edges, {len(metas)} sessions",
            f"跨 agent 谱系树{shown}：{len(roots)} 个根，{shown_edges} 条边，共 {len(metas)} 个会话"))
    for i, root in enumerate(roots):
        print()
        _render_node(root, "", children, i == len(roots) - 1)


def _render_node(meta: SessionMeta, prefix: str, children: dict, is_last: bool) -> None:
    connector = "└── " if is_last else "├── "
    label = (f"{session_key(meta)[:24]} {truncate(meta.title) or _t('(untitled)', '(无标题)')} "
             f"{_t(f'({meta.turns} turns)', f'（{meta.turns} 轮）')}")
    print(f"{prefix}{connector}{label}")
    kid_prefix = prefix + ("    " if is_last else "│   ")
    kids = sorted(children.get(session_key(meta), []), key=lambda m: m.last_active_at, reverse=True)
    for i, kid in enumerate(kids):
        _render_node(kid, kid_prefix, children, i == len(kids) - 1)
