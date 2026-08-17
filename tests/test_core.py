"""Core unit tests: ref resolution, session detection, atomic writes, utilities."""

import os
import tempfile
import unittest
from pathlib import Path

from caf.core import (
    CafxError,
    SessionMeta,
    Turn,
    atomic_write,
    encode_cwd,
    parse_session_ref,
    pick_recent_session,
    slice_turns,
)


class FakeAdapter:
    agent_id = "cc"

    def __init__(self, metas):
        self._metas = metas

    def scan_sessions(self):
        return self._metas

    def find_session(self, sid):
        for m in self._metas:
            if m.session_id.startswith(sid) or sid.startswith(m.session_id):
                return m
        return None


class CoreTest(unittest.TestCase):
    def test_cwd_encode_decode(self):
        self.assertEqual(encode_cwd("/tmp/fixture-proj"), "-tmp-fixture-proj")
        # verified CC rule: every non-ASCII char -> '-' (decode is ambiguous; always trust event cwd)
        self.assertEqual(encode_cwd("/tmp/中文项目"), "-tmp-----")
        self.assertEqual(
            encode_cwd("/Users/russeell/Documents/开源项目开发/jobfindsme"),
            "-Users-russeell-Documents--------jobfindsme",
        )

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
        with self.assertRaises(CafxError) as ctx:
            parse_session_ref("zzz", adapters)
        self.assertTrue(ctx.exception.hint)

    def test_pick_recent(self):
        old = SessionMeta("cc", "a", turns=1, last_active_at=100)
        new = SessionMeta("codex", "b", turns=1, last_active_at=200)
        picked = pick_recent_session([FakeAdapter([old]), FakeAdapter([new])])
        self.assertEqual(picked.session_id, "b")

    def test_pick_recent_project_filter(self):
        here = SessionMeta("cc", "a", turns=1, project_dir=os.getcwd(), last_active_at=100)
        other = SessionMeta("codex", "b", turns=1, project_dir="/elsewhere", last_active_at=999)
        picked = pick_recent_session([FakeAdapter([here, other])], project_dir=os.getcwd())
        self.assertEqual(picked.session_id, "a")

    def test_pick_recent_skips_empty(self):
        empty = SessionMeta("cc", "a", turns=0, last_active_at=999)
        real = SessionMeta("cc", "b", turns=5, last_active_at=100)
        picked = pick_recent_session([FakeAdapter([empty, real])])
        self.assertEqual(picked.session_id, "b")

    def _turns(self, n: int):
        """Build n complete turns (user + assistant alternating)."""
        out = []
        for i in range(1, n + 1):
            out.append(Turn(len(out) + 1, "user", f"u{i}"))
            out.append(Turn(len(out) + 1, "assistant", f"a{i}"))
        return out

    def test_slice_through(self):
        turns = self._turns(5)
        sliced, warning = slice_turns(turns, 3, "through")
        self.assertEqual(len(sliced), 6)  # u1..u3 + a1..a3
        self.assertEqual(sliced[-1].text, "a3")
        self.assertIsNone(warning)

    def test_slice_before(self):
        turns = self._turns(5)
        sliced, _ = slice_turns(turns, 3, "before")
        self.assertEqual(len(sliced), 4)  # 到 u2+a2
        self.assertEqual(sliced[-1].text, "a2")

    def test_slice_incomplete_turn(self):
        turns = self._turns(3) + [Turn(7, "user", "u4-未完成")]
        sliced, warning = slice_turns(turns, 4, "through")
        self.assertEqual(len(sliced), 6)
        self.assertIn("unfinished", warning)

    def test_slice_out_of_range(self):
        turns = self._turns(2)
        with self.assertRaises(CafxError):
            slice_turns(turns, 5, "through")

    def test_slice_at_zero(self):
        turns = self._turns(2)
        with self.assertRaises(CafxError):
            slice_turns(turns, 0, "through")

    def test_slice_before_one(self):
        turns = self._turns(2)
        with self.assertRaises(CafxError):
            slice_turns(turns, 1, "before")


if __name__ == "__main__":
    unittest.main()
