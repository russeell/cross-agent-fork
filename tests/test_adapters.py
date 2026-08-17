"""Adapter unit tests: CC read/write round-trip, Codex read, official import (mocked)."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caf.adapters.claude import ClaudeAdapter, encode_cwd
from caf.adapters.codex import (
    CodexAdapter,
    _parse_import_completed,
    import_external_session,
)
from caf.core import CafError, SessionIR, SessionMeta, Turn

FIXTURES = Path(__file__).parent / "fixtures"


class ClaudeAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        projects = Path(self.tmp) / "projects"
        d = projects / "-tmp-fixture-proj"
        d.mkdir(parents=True)
        shutil.copy(
            FIXTURES / "cc_sample.jsonl",
            d / "00000000-0000-0000-0000-00000000aa01.jsonl",
        )
        os.environ["CAF_CC_PROJECTS"] = str(projects)

    def tearDown(self):
        os.environ.pop("CAF_CC_PROJECTS", None)
        shutil.rmtree(self.tmp)

    def test_cwd_encode(self):
        """CC project-dir encoding: ASCII alnum kept, every non-ASCII char -> '-'."""
        self.assertEqual(encode_cwd("/tmp/fixture-proj"), "-tmp-fixture-proj")
        self.assertEqual(encode_cwd("/tmp/中文项目"), "-tmp-----")
        self.assertEqual(
            encode_cwd("/Users/russeell/Documents/开源项目开发/jobfindsme"),
            "-Users-russeell-Documents--------jobfindsme",
        )

    def test_scan(self):
        adapter = ClaudeAdapter()
        self.assertTrue(adapter.read_ready())
        metas = adapter.scan_sessions()
        self.assertEqual(len(metas), 1)
        meta = metas[0]
        self.assertEqual(meta.title, "OAuth 重构")
        self.assertEqual(meta.project_dir, "/tmp/fixture-proj")
        self.assertEqual(meta.turns, 2)

    def test_load(self):
        adapter = ClaudeAdapter()
        meta = adapter.scan_sessions()[0]
        ir = adapter.load_session(meta.session_id)
        self.assertEqual(len(ir.turns), 4)
        self.assertEqual(ir.turns[0].role, "user")
        self.assertIn("PKCE", ir.turns[0].text)
        self.assertEqual(ir.turns[1].tools[0].name, "Read")
        self.assertEqual(ir.turns[1].tools[0].file, "src/auth.py")

    def test_write_roundtrip(self):
        adapter = ClaudeAdapter()
        meta = adapter.scan_sessions()[0]
        ir = adapter.load_session(meta.session_id)
        new_id = adapter.write(ir)
        reloaded = ClaudeAdapter().load_session(
            new_id
        )  # fresh instance: no stale scan cache
        self.assertEqual(len(reloaded.turns), 4)
        self.assertIn("[tool] Read · ok · src/auth.py", reloaded.turns[1].text)
        cmd = adapter.resume_command(new_id, "/tmp/fixture-proj")
        self.assertIn("cd /tmp/fixture-proj && claude --resume", cmd)
        self.assertTrue(
            (Path(os.environ["CAF_CC_PROJECTS"]) / "-tmp-fixture-proj" / f"{new_id}.jsonl").is_file()
        )

    def test_write_creates_own_dir(self):
        adapter = ClaudeAdapter()
        ir = SessionIR(
            SessionMeta("codex", "src", project_dir="/other/project"),
            [],
        )
        new_id = adapter.write(ir)
        p = Path(os.environ["CAF_CC_PROJECTS"]) / "-other-project" / f"{new_id}.jsonl"
        self.assertTrue(p.is_file())

    def test_ai_title_priority(self):
        adapter = ClaudeAdapter()
        projects = Path(os.environ["CAF_CC_PROJECTS"])
        d = projects / "-tmp-ai-title-proj"
        d.mkdir(parents=True, exist_ok=True)
        (d / "aaaa0000-0000-0000-0000-000000000001.jsonl").write_text(
            "".join(
                [
                    '{"type":"summary","summary":"旧标题","cwd":"/tmp/ai-title-proj"}\n',
                    '{"type":"ai-title","aiTitle":"新标题","sessionId":"a"}\n',
                    '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"第一条用户消息内容很长"}]},"cwd":"/tmp/ai-title-proj"}\n',
                ]
            ),
            encoding="utf-8",
        )
        metas = adapter.scan_sessions()
        meta = next(m for m in metas if m.session_id.startswith("aaaa0000"))
        self.assertEqual(meta.title, "新标题")

    def test_title_falls_back_to_first_user(self):
        adapter = ClaudeAdapter()
        projects = Path(os.environ["CAF_CC_PROJECTS"])
        d = projects / "-tmp-no-title-proj"
        d.mkdir(parents=True, exist_ok=True)
        (d / "bbbb0000-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"帮我规划 9 天内完成转行 AI 应用工程师的学习计划，包含算法"}]},"cwd":"/tmp/no-title-proj"}\n',
            encoding="utf-8",
        )
        metas = adapter.scan_sessions()
        meta = next(m for m in metas if m.session_id.startswith("bbbb0000"))
        self.assertIn("帮我规划", meta.title)
        self.assertLessEqual(len(meta.title), 80)


class CodexAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CAF_CC_PROJECTS"] = str(Path(self.tmp) / "cc-projects")
        home = Path(self.tmp) / "codex"
        d = home / "sessions" / "2026" / "08" / "01"
        d.mkdir(parents=True)
        shutil.copy(
            FIXTURES / "codex_sample.jsonl",
            d
            / "rollout-2026-08-01T10-00-00-019e0000-0000-0000-0000-000000000001.jsonl",
        )
        (home / "session_index.jsonl").write_text(
            json.dumps(
                {
                    "id": "019e0000-0000-0000-0000-000000000001",
                    "thread_name": "OAuth 重构",
                    "updated_at": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["CAF_CODEX_HOME"] = str(home)
        # write() requires a codex binary; mock it so tests run without a local install
        self._codex_bin = mock.patch(
            "caf.adapters.codex._codex_bin", return_value="/usr/bin/codex"
        )
        self._codex_bin.start()

    def tearDown(self):
        self._codex_bin.stop()
        os.environ.pop("CAF_CODEX_HOME", None)
        os.environ.pop("CAF_CC_PROJECTS", None)
        shutil.rmtree(self.tmp)

    def test_scan(self):
        adapter = CodexAdapter()
        self.assertTrue(adapter.read_ready())
        metas = adapter.scan_sessions()
        self.assertEqual(len(metas), 1)
        meta = metas[0]
        self.assertEqual(meta.title, "OAuth 重构")
        self.assertEqual(meta.project_dir, "/tmp/fixture-proj")
        self.assertEqual(meta.turns, 1)

    def test_scan_uses_threads_table(self):
        import sqlite3

        db = Path(os.environ["CAF_CODEX_HOME"]) / "state_5.sqlite"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, "
            "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, source TEXT NOT NULL, "
            "model_provider TEXT NOT NULL, cwd TEXT NOT NULL, title TEXT NOT NULL, "
            "sandbox_policy TEXT NOT NULL, approval_mode TEXT NOT NULL, tokens_used INTEGER DEFAULT 0, "
            "has_user_event INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, cli_version TEXT DEFAULT '', "
            "updated_at_ms INTEGER, preview TEXT DEFAULT '')"
        )
        con.execute(
            "INSERT INTO threads (id, rollout_path, created_at, updated_at, source, model_provider, "
            "cwd, title, sandbox_policy, approval_mode, has_user_event) VALUES (?, ?, 0, 0, 'cli', "
            "'openai', ?, ?, 'none', 'never', 1)",
            (
                "019e0000-0000-0000-0000-000000000001",
                "/tmp/fake.jsonl",
                "/tmp/fixture-proj",
                "来自 threads 表的标题",
            ),
        )
        con.commit()
        con.close()

        adapter = CodexAdapter()
        metas = adapter.scan_sessions()
        self.assertEqual(len(metas), 1)
        self.assertEqual(metas[0].title, "来自 threads 表的标题")
        self.assertEqual(metas[0].project_dir, "/tmp/fixture-proj")

    def test_load(self):
        adapter = CodexAdapter()
        meta = adapter.scan_sessions()[0]
        ir = adapter.load_session(meta.session_id)
        self.assertEqual(len(ir.turns), 2)
        self.assertEqual(ir.turns[0].role, "user")
        self.assertIn("PKCE", ir.turns[0].text)

    @mock.patch(
        "caf.adapters.codex.import_external_session", return_value="019e-fake-thread"
    )
    def test_write_official_import(self, imp):
        adapter = CodexAdapter()
        src = Path(self.tmp) / "x.jsonl"
        src.write_text("{}", encoding="utf-8")
        ir = SessionIR(
            SessionMeta(
                "claude", "src", project_dir="/tmp/fixture-proj", source_path=str(src)
            ),
            [],
        )
        new_id = adapter.write(ir)
        imp.assert_called_once()
        self.assertEqual(new_id, "019e-fake-thread")

    def test_write_bridges_non_cc_source(self):
        """Non-CC source (e.g. DSH) -> render CC mirror -> official import -> mirror cleanup."""
        adapter = CodexAdapter()
        from unittest import mock as _mock

        with _mock.patch(
            "caf.adapters.codex.import_external_session",
            return_value="019e-bridged-thread",
        ) as imp:
            ir = SessionIR(
                SessionMeta(
                    "dsh",
                    "session-abc",
                    title="DSH 会话",
                    project_dir="/tmp/fixture-proj",
                ),
                [Turn("user", "你好"), Turn("assistant", "你好！")],
            )
            new_id = adapter.write(ir)
        self.assertEqual(new_id, "019e-bridged-thread")
        arg_source = imp.call_args.args[0]
        self.assertIn("__caf_bridge__", arg_source)
        self.assertFalse(Path(arg_source).exists())  # 用完即删

    def test_write_bridges_modified_ir(self):
        """CC source but IR was sliced (--at) -> must use the mirror bridge, not the source file."""
        adapter = CodexAdapter()
        from unittest import mock as _mock

        src = Path(os.environ["CAF_CC_PROJECTS"]) / "-tmp-x" / "src.jsonl"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("{}", encoding="utf-8")
        with _mock.patch(
            "caf.adapters.codex.import_external_session",
            return_value="019e-modified-thread",
        ) as imp:
            ir = SessionIR(
                SessionMeta(
                    "cc",
                    "9f3a12",
                    project_dir="/tmp/fixture-proj",
                    source_path=str(src),
                ),
                [Turn("user", "u1"), Turn("assistant", "a1")],
                modified=True,
            )
            adapter.write(ir)
        arg_source = imp.call_args.args[0]
        self.assertIn("__caf_bridge__", arg_source)

    def test_at_boundary_mirror_content(self):
        """Sliced IR -> correct mirror line count (--at end-to-end)."""
        from caf.core import slice_turns

        captured: dict = {}

        def fake_import(source, cwd):
            captured["lines"] = Path(source).read_text(encoding="utf-8").splitlines()
            return "019e-mirror-ok"

        from unittest import mock as _mock

        ir = SessionIR(
            SessionMeta("cc", "9f3a12", title="t", project_dir="/tmp/fixture-proj"),
            [
                Turn("user", "u1"),
                Turn("assistant", "a1"),
                Turn("user", "u2"),
                Turn("assistant", "a2"),
            ],
        )
        ir.turns, _ = slice_turns(ir.turns, 1)
        ir.modified = True
        with _mock.patch(
            "caf.adapters.codex.import_external_session", side_effect=fake_import
        ):
            from caf.adapters.codex import CodexAdapter as CA

            new_id = CA().write(ir)
        self.assertEqual(new_id, "019e-mirror-ok")
        lines = captured["lines"]
        self.assertEqual(len(lines), 5)  # queue-op×2 + summary + user + assistant
        self.assertNotIn("u2", "\n".join(lines))  # 边界外的轮次不在镜像里

    def test_parse_import_completed(self):
        params = {
            "importId": "i1",
            "itemTypeResults": [
                {
                    "itemType": "SESSIONS",
                    "successes": [
                        {
                            "itemType": "SESSIONS",
                            "cwd": "/tmp/p",
                            "source": "x.jsonl",
                            "target": "019e-thread",
                            "title": "OAuth 重构",
                        },
                    ],
                    "failures": [],
                },
            ],
        }
        self.assertEqual(_parse_import_completed(params), "019e-thread")

    def test_parse_import_failure(self):
        params = {
            "importId": "i1",
            "itemTypeResults": [
                {
                    "itemType": "SESSIONS",
                    "successes": [],
                    "failures": [
                        {
                            "itemType": "SESSIONS",
                            "errorType": "parse",
                            "failureStage": "ingest",
                            "message": "bad file",
                        }
                    ],
                },
            ],
        }
        with self.assertRaises(Exception) as ctx:
            _parse_import_completed(params)
        self.assertIn("bad file", str(ctx.exception))

    def test_resume_command(self):
        adapter = CodexAdapter()
        cmd = adapter.resume_command("abc", "/tmp/p")
        self.assertIn("cd /tmp/p && codex resume abc", cmd)


class AmbiguityTest(unittest.TestCase):
    """Prefix ambiguity: threads created in the same millisecond share UUIDv7 timestamp prefixes."""

    def test_find_session_ambiguous(self):
        from caf.adapters import Adapter
        from caf.core import CafError

        class TwoSessionsAdapter(Adapter):
            agent_id = "codex"

            def read_ready(self):
                return True

            def write_ready(self):
                return True

            def scan_sessions(self):
                return [
                    SessionMeta(
                        "codex", "019f6621-31ff-7160-8c4e-8f9303746637", turns=1
                    ),
                    SessionMeta(
                        "codex", "019f6621-32af-7df0-940c-0deb280ebd89", turns=2
                    ),
                ]

        adapter = TwoSessionsAdapter()
        with self.assertRaises(CafError):
            adapter.find_session("019f6621")
        # a long enough prefix resolves precisely
        meta = adapter.find_session("019f6621-31ff")
        self.assertEqual(meta.session_id, "019f6621-31ff-7160-8c4e-8f9303746637")


class CodexImportRpcTest(unittest.TestCase):
    """Official import RPC paths: success / JSON-RPC error / timeout (fake app-server)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = Path(self.tmp) / "fake_codex.py"
        shutil.copy(FIXTURES / "fake_codex.py", self.fake)
        os.chmod(self.fake, 0o755)
        self.src = Path(self.tmp) / "src.jsonl"
        self.src.write_text("{}", encoding="utf-8")
        os.environ["CAF_CODEX_BIN"] = str(self.fake)

    def tearDown(self):
        os.environ.pop("CAF_CODEX_BIN", None)
        os.environ.pop("FAKE_CODEX_MODE", None)
        shutil.rmtree(self.tmp)

    def _run(self, mode: str, timeout_s: int = 10) -> str:
        os.environ["FAKE_CODEX_MODE"] = mode
        return import_external_session(str(self.src), "/tmp", timeout_s=timeout_s)

    def test_import_success(self):
        self.assertEqual(self._run("ok"), "thread-123")

    def test_import_rpc_error(self):
        with self.assertRaises(CafError) as ctx:
            self._run("error")
        self.assertIn("-32601", str(ctx.exception))

    def test_import_timeout(self):
        with self.assertRaises(CafError) as ctx:
            self._run("timeout", timeout_s=2)
        self.assertIn("Timed out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
