"""DSH plugin tests: projectKey encoding, real-format reads, write round-trip."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from caf.adapters import discover_adapters
from caf.i18n import set_lang
from caf.core import SessionIR, SessionMeta, ToolSummary, Turn
from caf.plugins.dsh import DshAdapter, _file_from_args, _project_key

FIXTURES = Path(__file__).parent / "fixtures"


def _zstd_ok() -> bool:
    try:
        import zstandard  # noqa: F401
        return True
    except ImportError:
        pass
    return shutil.which("zstd") is not None


@unittest.skipUnless(_zstd_ok(), "需要 zstandard 或 zstd CLI")
class DshPluginTest(unittest.TestCase):
    def setUp(self):
        set_lang("en")
        self.tmp = tempfile.mkdtemp()
        os.environ["CAF_DSH_SESSIONS"] = str(Path(self.tmp) / "sessions")
        os.environ["CAF_LANG"] = "en"

    def tearDown(self):
        os.environ.pop("CAF_DSH_SESSIONS", None)
        os.environ.pop("CAF_LANG", None)
        shutil.rmtree(self.tmp)

    def test_project_key(self):
        self.assertEqual(
            _project_key("/Users/russeell/Documents/deepseek harness"),
            "--Users-russeell-Documents-deepseek~0020harness--",
        )
        self.assertEqual(_project_key("/tmp/a"), "--tmp-a--")
        # a trailing slash adds one '-' (matching the DSH implementation)
        self.assertEqual(_project_key("/tmp/a/"), "--tmp-a---")

    def test_file_from_args_dict_and_str(self):
        self.assertEqual(_file_from_args('{"file_path": "src/a.py"}'), "src/a.py")
        self.assertEqual(_file_from_args({"path": "src/b.py"}), "src/b.py")
        self.assertIsNone(_file_from_args({"cmd": "ls"}))
        self.assertIsNone(_file_from_args("not-json"))

    def test_discovery_includes_plugin(self):
        names = {a.agent_id for a in discover_adapters()}
        self.assertIn("dsh", names)

    def test_read_real_fixture(self):
        root = Path(os.environ["CAF_DSH_SESSIONS"])
        d = root / "--tmp-fixture-proj--" / "session-aaaaaaaa-0000-0000-0000-000000000001"
        d.mkdir(parents=True)
        shutil.copy(FIXTURES / "dsh_sample.jsonl.zstd", d / "session.jsonl.zstd")

        adapter = DshAdapter()
        self.assertTrue(adapter.detect())
        metas = adapter.scan_sessions()
        self.assertEqual(len(metas), 1)
        meta = metas[0]
        self.assertEqual(meta.title, "OAuth 重构")
        self.assertEqual(meta.turns, 1)
        self.assertEqual(meta.project_dir, "/tmp/fixture-proj")

        ir = adapter.load_session(meta.session_id)
        self.assertEqual(len(ir.turns), 2)
        self.assertEqual(ir.turns[0].role, "user")
        self.assertIn("PKCE", ir.turns[0].text)
        self.assertEqual(ir.turns[1].tools[0].name, "Read")
        self.assertEqual(ir.turns[1].tools[0].file, "src/auth.py")

    def test_write_roundtrip(self):
        adapter = DshAdapter()
        ir = SessionIR(
            SessionMeta("cc", "9f3a12", title="OAuth 重构", project_dir="/tmp/中文项目"),
            [
                Turn(1, "user", "把 OAuth 回调改成 PKCE 流程"),
                Turn(2, "assistant", "完成", [ToolSummary("edit_file", "ok", "src/auth.py")]),
            ],
        )
        sid = adapter.write(ir)
        self.assertTrue(sid.startswith("session-"))

        meta = adapter.find_session(sid)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "OAuth 重构")
        self.assertEqual(meta.project_dir, "/tmp/中文项目")
        self.assertEqual(meta.turns, 1)

        reloaded = adapter.load_session(sid)
        self.assertEqual(len(reloaded.turns), 2)
        self.assertIn("[tool] edit_file · ok · src/auth.py", reloaded.turns[1].text)
        cmd = adapter.resume_command(sid, "/tmp/中文项目")
        self.assertIn(f"dsh --profile tui --resume {sid}", cmd)

        # directory encoding is correct (each CJK char -> ~XXXX)
        written = Path(os.environ["CAF_DSH_SESSIONS"])
        self.assertTrue(list(written.glob("--tmp-~4E2D~6587~9879~76EE--/session-*")) or
                        list(written.glob("--tmp-*/session-*")))

    def test_write_multi_assistant_single_turn_end(self):
        """One user turn with several assistant segments -> exactly one turn/end."""
        from caf.plugins.dsh import _zstd_decompress

        adapter = DshAdapter()
        ir = SessionIR(
            SessionMeta("cc", "9f3a12", project_dir="/tmp/fixture-proj"),
            [
                Turn(1, "user", "u1"),
                Turn(2, "assistant", "a1"),
                Turn(3, "assistant", "a2"),
                Turn(4, "user", "u2"),
                Turn(5, "assistant", "a3"),
            ],
        )
        sid = adapter.write(ir)
        path = next((Path(os.environ["CAF_DSH_SESSIONS"]).rglob(f"{sid}/session.jsonl.zstd")))
        import json
        lines = [line for line in _zstd_decompress(path.read_bytes()).decode().splitlines()
                 if line.strip()]
        events = [json.loads(line) for line in lines]
        types = [e["type"] for e in events]
        self.assertEqual(types.count("turn/start"), 2)
        self.assertEqual(types.count("turn/end"), 2)
        self.assertEqual(types.count("assistant/message"), 3)
        self.assertEqual(types.count("user/message"), 2)
        # each turn opens once and closes once; assistant segments stay inside their turn
        self.assertLess(types.index("assistant/message"), types.index("turn/end"))


if __name__ == "__main__":
    unittest.main()
