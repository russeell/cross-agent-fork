"""DSH adapter tests: projectKey encoding, real-format reads, write round-trip."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from caf.adapters import discover_adapters
from caf.core import CafError, ForkSnapshot, SessionMeta, Turn
from caf.adapters.dsh import DshAdapter, _argument_text, _project_key

FIXTURES = Path(__file__).parent / "fixtures"


class DshAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        Path("/tmp/fixture-proj").mkdir(parents=True, exist_ok=True)
        os.environ["CAF_DSH_SESSIONS"] = str(Path(self.tmp) / "sessions")
        os.environ["DSH_HOME"] = str(Path(self.tmp) / "dsh-home")
        (Path(os.environ["DSH_HOME"]) / "profiles" / "tui").mkdir(parents=True)

    def tearDown(self):
        os.environ.pop("CAF_DSH_SESSIONS", None)
        os.environ.pop("DSH_HOME", None)
        shutil.rmtree(self.tmp)

    def test_resume_web_only_without_tui_profile(self):
        """web-only dsh installs (no tui profile) get a GUI resume hint, not a dead command."""
        from caf.adapters.dsh import DshAdapter

        tui_dir = Path(os.environ["DSH_HOME"]) / "profiles" / "tui"
        tui_dir.rmdir()  # simulate a web-only install
        adapter = DshAdapter()
        cmd = adapter.resume_command("session-abc", "/tmp/fixture-proj")
        self.assertIn("http://127.0.0.1:3080", cmd)
        self.assertNotIn("--profile tui", cmd)
        tui_dir.mkdir()  # restore: with a tui profile the CLI resume form is used
        self.assertIn(
            "dsh --profile tui --resume session-abc",
            adapter.resume_command("session-abc", "/tmp/fixture-proj"),
        )

    def test_project_key(self):
        self.assertEqual(
            _project_key("/Users/russeell/Documents/deepseek harness"),
            "--Users-russeell-Documents-deepseek~0020harness--",
        )
        self.assertEqual(_project_key("/tmp/a"), "--tmp-a--")
        # a trailing slash adds one '-' (matching the DSH implementation)
        self.assertEqual(_project_key("/tmp/a/"), "--tmp-a---")

    def test_tool_arguments_dict_is_json(self):
        self.assertEqual(_argument_text({"path": "src/b.py"}), '{"path": "src/b.py"}')

    def test_discovery_includes_adapter(self):
        names = {a.agent_id for a in discover_adapters()}
        self.assertIn("dsh", names)

    def test_read_real_fixture(self):
        root = Path(os.environ["CAF_DSH_SESSIONS"])
        d = (
            root
            / "--tmp-fixture-proj--"
            / "session-aaaaaaaa-0000-0000-0000-000000000001"
        )
        d.mkdir(parents=True)
        shutil.copy(FIXTURES / "dsh_sample.jsonl.zstd", d / "session.jsonl.zstd")

        adapter = DshAdapter()
        self.assertTrue(adapter.read_ready())
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
        self.assertIn("[tool] Read", ir.turns[1].text)
        self.assertIn("src/auth.py", ir.turns[1].text)
        self.assertIn("[tool result] Read · ok", ir.turns[1].text)
        self.assertIn("...", ir.turns[1].text)
        self.assertEqual(ir.unfinished_turns, set())

    def test_write_roundtrip(self):
        adapter = DshAdapter()
        project = Path(self.tmp) / "中文项目"
        project.mkdir(parents=True, exist_ok=True)
        ir = ForkSnapshot(
            SessionMeta("cc", "9f3a12", title="OAuth 重构", project_dir=str(project)),
            [
                Turn("user", "把 OAuth 回调改成 PKCE 流程"),
                Turn("assistant", "完成\n[tool] edit_file"),
            ],
        )
        sid = adapter.write(ir)
        self.assertTrue(sid.startswith("session-"))

        meta = adapter.find_session(sid)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "OAuth 重构")
        self.assertEqual(meta.project_dir, str(project))
        self.assertEqual(meta.turns, 1)

        reloaded = adapter.load_session(sid)
        self.assertEqual(len(reloaded.turns), 2)
        self.assertIn("[tool] edit_file", reloaded.turns[1].text)
        cmd = adapter.resume_command(sid, str(project))
        self.assertIn(f"dsh --profile tui --resume {sid}", cmd)

        # directory encoding is correct (each CJK char -> ~XXXX)
        written = Path(os.environ["CAF_DSH_SESSIONS"]) / _project_key(str(project))
        self.assertTrue(list(written.glob("session-*/session.jsonl.zstd")))

    def test_write_rejects_unknown_cwd(self):
        with self.assertRaises(CafError):
            DshAdapter().write(ForkSnapshot(SessionMeta("cc", "src"), []))

    def test_write_one_frame_per_line(self):
        """DSH stores one zstd frame per JSON line; a single-frame log is rejected."""
        try:
            import zstandard as zstd
        except ImportError:
            self.skipTest("zstandard is required for frame-level checks")

        adapter = DshAdapter()
        ir = ForkSnapshot(
            SessionMeta("cc", "9f3a12", project_dir="/tmp/fixture-proj"),
            [Turn("user", "u1"), Turn("assistant", "a1")],
        )
        sid = adapter.write(ir)
        path = next(
            Path(os.environ["CAF_DSH_SESSIONS"]).rglob(f"{sid}/session.jsonl.zstd")
        )
        data = path.read_bytes()

        dctx = zstd.ZstdDecompressor()
        pos, payloads = 0, []
        while pos < len(data):
            dobj = dctx.decompressobj()
            payloads.append(dobj.decompress(data[pos:]))
            consumed = len(data) - pos - len(dobj.unused_data)
            self.assertGreater(consumed, 0)
            pos += consumed
        self.assertEqual(
            len(payloads), 5
        )  # header + turn/start + user + assistant + turn/end
        self.assertTrue(all(p.endswith(b"\n") and len(p.strip()) for p in payloads))
        self.assertIn(b'"type": "session"', payloads[0])
        import json

        events = [json.loads(p) for p in payloads[1:]]
        self.assertEqual(
            [e["seq"] for e in events], list(range(len(events)))
        )  # dsh: events[i].seq === i
        user = next(e for e in events if e["type"] == "user/message")
        self.assertNotEqual(user["data"]["id"], "")  # dsh: message events require an id
        self.assertEqual(
            user.get("surfaceOp"), "append"
        )  # dsh: surface events require the marker
        assistant = next(e for e in events if e["type"] == "assistant/message")
        self.assertNotEqual(assistant["data"]["message"]["id"], "")
        self.assertEqual(assistant.get("surfaceOp"), "append")

    def test_read_single_frame_still_compatible(self):
        """Old single-frame logs (pre-frame-per-line dsh) must still decompress."""
        from caf.adapters.dsh import _zstd_compress_frames, _zstd_decompress

        try:
            import zstandard as zstd
        except ImportError:
            self.skipTest("zstandard is required")

        raw = b'{"type":"session","version":0,"id":"session-x"}\n{"type":"turn/start","seq":1}\n'
        single = zstd.ZstdCompressor().compress(raw)
        self.assertEqual(_zstd_decompress(single), raw)
        self.assertEqual(_zstd_compress_frames([raw]), single)  # one chunk -> one frame

    def test_write_multi_assistant_single_turn_end(self):
        """One user turn with several assistant segments -> exactly one turn/end."""
        from caf.adapters.dsh import _zstd_decompress

        adapter = DshAdapter()
        ir = ForkSnapshot(
            SessionMeta("cc", "9f3a12", project_dir="/tmp/fixture-proj"),
            [
                Turn("user", "u1"),
                Turn("assistant", "a1"),
                Turn("assistant", "a2"),
                Turn("user", "u2"),
                Turn("assistant", "a3"),
            ],
        )
        sid = adapter.write(ir)
        path = next(
            (Path(os.environ["CAF_DSH_SESSIONS"]).rglob(f"{sid}/session.jsonl.zstd"))
        )
        import json

        lines = [
            line
            for line in _zstd_decompress(path.read_bytes()).decode().splitlines()
            if line.strip()
        ]
        events = [json.loads(line) for line in lines]
        types = [e["type"] for e in events]
        self.assertEqual(types.count("turn/start"), 2)
        self.assertEqual(types.count("turn/end"), 2)
        self.assertEqual(types.count("assistant/message"), 3)
        self.assertEqual(types.count("user/message"), 2)
        # each turn opens once and closes once; assistant segments stay inside their turn
        self.assertLess(types.index("assistant/message"), types.index("turn/end"))

    def test_decompress_tolerates_truncated_tail_frame(self):
        """A session mid-append must not vanish: complete frames are kept, an incomplete
        final frame is tolerated. A corrupt leading frame is still a hard failure."""
        from caf.adapters.dsh import _zstd_decompress

        try:
            import zstandard as zstd
        except ImportError:
            self.skipTest("zstandard is required")

        cctx = zstd.ZstdCompressor()
        f1 = cctx.compress(b'{"type":"user/message"}\n')
        f2 = cctx.compress(b'{"type":"assistant/message"}\n')
        tail = cctx.compress(b'{"type":"turn/end"}\n')[:12]  # truncated final frame
        out = _zstd_decompress(f1 + f2 + tail)
        self.assertEqual(
            out.decode().splitlines(),
            ['{"type":"user/message"}', '{"type":"assistant/message"}'],
        )

        with self.assertRaises(zstd.ZstdError):
            _zstd_decompress(b"\x28\xb5\x2f\xfd garbage")  # corrupt leading frame

    def test_scan_tolerates_truncated_tail_session(self):
        """Forking a session while the source agent appends the last zstd frame must not
        make the session disappear from scan (complete events are preserved)."""
        from caf.adapters.dsh import _project_key

        try:
            import zstandard as zstd
        except ImportError:
            self.skipTest("zstandard is required")

        import json as _json

        cctx = zstd.ZstdCompressor()
        header = {
            "type": "session",
            "version": 0,
            "id": "session-trunc1",
            "createdAt": 0,
            "cwd": "/tmp/fixture-proj",
        }
        f1 = cctx.compress((_json.dumps(header) + "\n").encode("utf-8"))
        f2 = cctx.compress(
            b'{"type":"user/message","seq":1,"data":{"content":[{"type":"text",'
            b'"text":"u1"}],"source":{"kind":"user"}}}\n'
        )
        tail = cctx.compress(b'{"type":"assistant/message"}\n')[:8]
        root = Path(os.environ["CAF_DSH_SESSIONS"])
        d = root / _project_key("/tmp/fixture-proj") / "session-trunc1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "session.jsonl.zstd").write_bytes(f1 + f2 + tail)

        metas = DshAdapter().scan_sessions()
        self.assertTrue(any(m.session_id == "session-trunc1" for m in metas))
        meta = next(m for m in metas if m.session_id == "session-trunc1")
        self.assertEqual(meta.turns, 1)  # complete user message survived the tail cut


if __name__ == "__main__":
    unittest.main()
