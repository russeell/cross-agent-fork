"""Core unit tests: ref resolution, deterministic source pick, atomic writes, utilities."""

import os
import tempfile
import unittest
from pathlib import Path

from caf.core import (
    CafError,
    SessionMeta,
    ToolSummary,
    Turn,
    atomic_write,
    parse_session_ref,
    pick_recent_session,
    slice_turns,
    with_tool_lines,
)


class FakeAdapter:
    agent_id = "cc"

    def __init__(self, metas):
        self._metas = metas

    def read_ready(self):
        return True

    def scan_cached(self):
        return self._metas

    def scan_sessions(self):
        return self._metas

    def find_session(self, sid):
        for m in self._metas:
            if m.session_id.startswith(sid) or sid.startswith(m.session_id):
                return m
        return None


class CoreTest(unittest.TestCase):
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a" / "x.jsonl"
            atomic_write(p, "line1\n")
            self.assertEqual(p.read_text(), "line1\n")
            self.assertFalse(p.with_name("x.jsonl.tmp").exists())

    def test_parse_ref_named(self):
        adapters = [FakeAdapter([SessionMeta("cc", "9f3a12", last_active_at=1)])]
        self.assertEqual(parse_session_ref("cc:9f3a", adapters), ("cc", "9f3a"))
        self.assertEqual(parse_session_ref("9f3a123", adapters), ("cc", "9f3a123"))

    def test_parse_ref_unknown(self):
        adapters = [FakeAdapter([SessionMeta("cc", "9f3a12", last_active_at=1)])]
        with self.assertRaises(CafError) as ctx:
            parse_session_ref("zzz", adapters)
        self.assertTrue(ctx.exception.hint)

    def test_pick_recent(self):
        old = SessionMeta("cc", "a", turns=1, last_active_at=100)
        new = SessionMeta("codex", "b", turns=1, last_active_at=200)
        picked = pick_recent_session([FakeAdapter([old]), FakeAdapter([new])])
        self.assertEqual(picked.session_id, "b")

    def test_pick_recent_project_filter(self):
        here = SessionMeta(
            "cc", "a", turns=1, project_dir=os.getcwd(), last_active_at=100
        )
        other = SessionMeta(
            "codex", "b", turns=1, project_dir="/elsewhere", last_active_at=999
        )
        picked = pick_recent_session(
            [FakeAdapter([here, other])], project_dir=os.getcwd()
        )
        self.assertEqual(picked.session_id, "a")

    def test_pick_recent_unknown_cwd_never_counts_as_current_project(self):
        """A session with project_dir=None must not win the current-directory pick."""
        unknown = SessionMeta("cc", "a", turns=1, project_dir=None, last_active_at=999)
        picked = pick_recent_session([FakeAdapter([unknown])], project_dir=os.getcwd())
        self.assertIsNone(picked)

    def test_parse_ref_bare_id_ambiguous_across_agents(self):
        """A bare id matching sessions in several adapters must error, not pick the first."""
        adapters = [
            FakeAdapter([SessionMeta("cc", "abc123", last_active_at=1)]),
            FakeAdapter([SessionMeta("codex", "abc456", last_active_at=1)]),
        ]
        with self.assertRaises(CafError):
            parse_session_ref("abc", adapters)

    def test_with_tool_lines_canonical(self):
        """Envelope text uses canonical English tokens."""
        text = with_tool_lines("", [ToolSummary("edit_file", "ok", "src/auth.py")])
        self.assertEqual(text, "[tool] edit_file · ok · src/auth.py")

    def test_pick_recent_skips_empty(self):
        empty = SessionMeta("cc", "a", turns=0, last_active_at=999)
        real = SessionMeta("cc", "b", turns=5, last_active_at=100)
        picked = pick_recent_session([FakeAdapter([empty, real])])
        self.assertEqual(picked.session_id, "b")

    def _turns(self, n: int):
        """Build n complete turns (user + assistant alternating)."""
        out = []
        for i in range(1, n + 1):
            out.append(Turn("user", f"u{i}"))
            out.append(Turn("assistant", f"a{i}"))
        return out

    def test_slice_through(self):
        turns = self._turns(5)
        sliced, warning = slice_turns(turns, 3)
        self.assertEqual(len(sliced), 6)  # u1..u3 + a1..a3
        self.assertEqual(sliced[-1].text, "a3")
        self.assertIsNone(warning)

    def test_slice_incomplete_turn(self):
        turns = self._turns(3) + [Turn("user", "u4-未完成")]
        sliced, warning = slice_turns(turns, 4)
        self.assertEqual(len(sliced), 6)
        self.assertIn("unfinished", warning)

    def test_slice_includes_all_assistant_segments(self):
        """Turn N = user N plus everything up to the next user (tool loops produce several assistants)."""
        turns = [
            Turn("user", "u1"),
            Turn("assistant", "a1"),
            Turn("assistant", "a2"),
            Turn("user", "u2"),
            Turn("assistant", "a3"),
        ]
        sliced, warning = slice_turns(turns, 1)
        self.assertEqual([t.text for t in sliced], ["u1", "a1", "a2"])
        self.assertIsNone(warning)
        sliced2, _ = slice_turns(turns, 2)
        self.assertEqual([t.text for t in sliced2], ["u1", "a1", "a2", "u2", "a3"])

    def test_slice_consecutive_users_keeps_only_user_n(self):
        """Multi-part input (user N directly followed by user N+1): turn N is just user N."""
        turns = [Turn("user", "u1"), Turn("user", "u2"), Turn("assistant", "a2")]
        sliced, _ = slice_turns(turns, 1)
        self.assertEqual([t.text for t in sliced], ["u1"])

    def test_slice_out_of_range(self):
        turns = self._turns(2)
        with self.assertRaises(CafError):
            slice_turns(turns, 5)

    def test_slice_at_zero(self):
        turns = self._turns(2)
        with self.assertRaises(CafError):
            slice_turns(turns, 0)


if __name__ == "__main__":
    unittest.main()
