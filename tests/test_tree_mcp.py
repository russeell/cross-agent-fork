"""v0.2 tests: caf tree (lineage) + caf mcp (stdio server)."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import caf.cli as cli_mod
from caf.core import SessionMeta
from caf.i18n import set_lang

FIXTURES = Path(__file__).parent / "fixtures"


class FakeAdapter:
    def __init__(self, metas):
        self._metas = metas
        self.agent_id = metas[0].provider_id if metas else "fake"

    def scan_sessions(self):
        return self._metas

    def detect(self):
        return True


class TreeTest(unittest.TestCase):
    def test_tree_renders_lineage(self):
        a = SessionMeta("cc", "aaa11111-0000", title="Root session", turns=3)
        b = SessionMeta("codex", "bbb22222-0000", title="Child session", turns=2,
                        parent_ref="cc:aaa11111")
        c = SessionMeta("dsh", "session-ccc33333", title="Grandchild session", turns=1,
                        parent_ref="codex:bbb22222")
        old = cli_mod.discover_adapters
        cli_mod.discover_adapters = lambda: [FakeAdapter([a, b, c])]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cli_mod.cmd_tree(type("A", (), {"json": False})())
        finally:
            cli_mod.discover_adapters = old
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("cc:aaa11111-0000", text)
        self.assertIn("codex:bbb22222-0000", text)
        self.assertIn("dsh:session-ccc33333", text)
        self.assertIn("1 roots", text)

    def test_tree_json(self):
        a = SessionMeta("cc", "aaa11111-0000", turns=1)
        b = SessionMeta("codex", "bbb22222-0000", turns=1, parent_ref="cc:aaa11111")
        old = cli_mod.discover_adapters
        cli_mod.discover_adapters = lambda: [FakeAdapter([a, b])]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli_mod.cmd_tree(type("A", (), {"json": True})())
        finally:
            cli_mod.discover_adapters = old
        data = json.loads(out.getvalue())
        self.assertEqual(data["roots"], ["cc:aaa11111-0000"])
        self.assertEqual(data["edges"],
                         [{"child": "codex:bbb22222-0000", "parent": "cc:aaa11111-0000",
                           "cross": True}])

    def test_tree_hides_same_agent_edges_by_default(self):
        a = SessionMeta("cc", "aaa11111-0000", turns=1)
        b = SessionMeta("cc", "bbb22222-0000", turns=1, parent_ref="cc:aaa11111")
        c = SessionMeta("dsh", "session-ccc33333", turns=1, parent_ref="cc:bbb22222")
        old = cli_mod.discover_adapters
        cli_mod.discover_adapters = lambda: [FakeAdapter([a, b, c])]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli_mod.cmd_tree(type("A", (), {"json": True, "all": False})())
        finally:
            cli_mod.discover_adapters = old
        data = json.loads(out.getvalue())
        # same-agent edges (cc->cc) hidden by default: b becomes a root; cross-agent edges kept
        self.assertIn("cc:bbb22222-0000", data["roots"])
        self.assertIn({"child": "dsh:session-ccc33333", "parent": "cc:bbb22222-0000",
                       "cross": True}, data["edges"])


class McpTest(unittest.TestCase):
    def setUp(self):
        set_lang("en")
        self.tmp = tempfile.mkdtemp()
        projects = Path(self.tmp) / "projects"
        (projects / "-tmp-fixture-proj").mkdir(parents=True)
        shutil.copy(FIXTURES / "cc_sample.jsonl",
                    projects / "-tmp-fixture-proj" / "00000000-0000-0000-0000-00000000aa01.jsonl")
        codex = Path(self.tmp) / "codex"
        (codex / "sessions" / "2026" / "08" / "01").mkdir(parents=True)
        shutil.copy(FIXTURES / "codex_sample.jsonl",
                    codex / "sessions" / "2026" / "08" / "01"
                    / "rollout-2026-08-01T10-00-00-019e0000-0000-0000-0000-000000000001.jsonl")
        os.environ.update({
            "CAF_CC_PROJECTS": str(projects),
            "CAF_CODEX_HOME": str(codex),
            "CAF_DSH_SESSIONS": str(Path(self.tmp) / "no-dsh"),
            "CAF_LANG": "en",
        })
        Path("/tmp/fixture-proj").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for k in ("CAF_CC_PROJECTS", "CAF_CODEX_HOME", "CAF_DSH_SESSIONS"):
            os.environ.pop(k, None)
        os.environ.pop("CAF_LANG", None)
        shutil.rmtree("/tmp/fixture-proj", ignore_errors=True)
        shutil.rmtree(self.tmp)

    def _converse(self, messages: list[dict]) -> list[dict]:
        from caf.mcp import serve
        feed = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
        out = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = feed
        try:
            with contextlib.redirect_stdout(out):
                serve()
        finally:
            sys.stdin = old_stdin
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    def test_mcp_handshake_list_call(self):
        responses = self._converse([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "caf_list", "arguments": {"all": True}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "caf_doctor", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown"},
        ])
        by_id = {r.get("id"): r for r in responses}
        self.assertIn("caf", json.dumps(by_id[1]["result"]["serverInfo"]["name"]))
        tool_names = [t["name"] for t in by_id[2]["result"]["tools"]]
        self.assertEqual(tool_names, ["caf_list", "caf_fork", "caf_tree", "caf_doctor"])
        list_text = by_id[3]["result"]["content"][0]["text"]
        self.assertIn("cc:00000000", list_text)
        self.assertFalse(by_id[3]["result"]["isError"])
        doc_text = by_id[4]["result"]["content"][0]["text"]
        self.assertIn("claude", doc_text)


if __name__ == "__main__":
    unittest.main()
