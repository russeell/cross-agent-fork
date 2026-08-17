"""CLI smoke tests: list / fork --dry-run / doctor (fixtures + env isolation)."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caf.cli import main
from caf.i18n import set_lang

FIXTURES = Path(__file__).parent / "fixtures"


def _run(argv: list[str], env_overrides: dict | None = None) -> tuple[int, str]:
    buf = io.StringIO()
    saved = {}
    if env_overrides:
        for k, v in env_overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
    with contextlib.redirect_stdout(buf):
        try:
            code = main(argv)
        finally:
            if env_overrides:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
    return code, buf.getvalue()


class CliTest(unittest.TestCase):
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
        (codex / "session_index.jsonl").write_text(
            json.dumps({"id": "019e0000-0000-0000-0000-000000000001",
                        "thread_name": "OAuth 重构", "updated_at": 1}) + "\n",
            encoding="utf-8",
        )
        Path("/tmp/fixture-proj").mkdir(parents=True, exist_ok=True)  # fixture 会话的 cwd
        self.env = {
            "CAF_CC_PROJECTS": str(projects),
            "CAF_CODEX_HOME": str(codex),
            "CAF_DSH_SESSIONS": str(Path(self.tmp) / "no-dsh"),  # isolate the real ~/.dsh
            "CAF_LANG": "en",
        }
        # fork tests exercise write_ready / resume paths; mock CLI presence so the
        # suite runs on CI without codex/claude installed
        self._cli_patches = [
            mock.patch("caf.adapters.codex._codex_bin", return_value="/usr/bin/codex"),
            mock.patch("caf.adapters.claude.shutil.which", return_value="/usr/bin/claude"),
        ]
        for p in self._cli_patches:
            p.start()
        self._old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for p in self._cli_patches:
            p.stop()
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree("/tmp/fixture-proj", ignore_errors=True)
        shutil.rmtree(self.tmp)

    def test_list_json(self):
        code, out = _run(["list", "--all", "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), 2)
        providers = {r["providerId"] for r in rows}
        self.assertEqual(providers, {"cc", "codex"})

    def test_list_claude_flag(self):
        code, out = _run(["list", "--claude", "--all"])
        self.assertEqual(code, 0)
        self.assertIn("cc:00000000", out)
        self.assertNotIn("codex:", out)
        self.assertNotIn("codex v", out)  # 发现行只显示过滤后的 agent

    def test_list_default_shows_all(self):
        import caf.cli as cli_mod
        old = cli_mod._stdout_isatty
        cli_mod._stdout_isatty = lambda: True  # TTY：显示引导行
        code, out = _run(["list"])
        cli_mod._stdout_isatty = old
        self.assertEqual(code, 0)
        self.assertIn("cc:00000000", out)
        self.assertIn("codex:019e0000", out)
        self.assertIn("-> fork the most recent: caf fork codex:019e0000", out)

    def test_list_pipe_output_is_clean(self):
        """Non-TTY (agent/pipe/chat): data only, no guidance lines."""
        code, out = _run(["list"])
        self.assertEqual(code, 0)
        self.assertNotIn("-> fork the most recent", out)
        self.assertNotIn("more:", out)
        self.assertIn("cc:00000000", out)
        self.assertIn("codex:019e0000", out)

    def test_list_table_has_no_row_numbers(self):
        """Stable-column table: identifiers leftmost, no '1.' prefix (chat Markdown safety)."""
        code, out = _run(["list"])
        self.assertEqual(code, 0)
        self.assertNotIn("1. codex:", out)
        self.assertIn("Session", out)  # header without '#'
        self.assertIn("  codex:019e0000", out)

    def test_list_limit_footer(self):
        import caf.cli as cli_mod
        old = cli_mod._stdout_isatty
        cli_mod._stdout_isatty = lambda: True
        projects = Path(os.environ["CAF_CC_PROJECTS"])
        d = projects / "-tmp-limit-proj"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(25):
            (d / f"aaaa{i:04d}-0000-0000-0000-000000000000.jsonl").write_text(
                '{"type":"user","message":{"role":"user","content":[{"type":"text",'
                f'"text":"会话 {i}"}}]}},"cwd":"/tmp/limit-proj"}}\n',
                encoding="utf-8",
            )
        code, out = _run(["list", "claude"])
        cli_mod._stdout_isatty = old
        self.assertEqual(code, 0)
        self.assertIn("26 sessions", out)
        self.assertIn("--all all", out)
        code_all, out_all = _run(["list", "claude", "--all"])
        self.assertEqual(code_all, 0)
        self.assertIn("aaaa0024", out_all)  # the 26th is visible
        self.assertNotIn("showing 20", out_all)

    def test_list_limit_flag(self):
        projects = Path(os.environ["CAF_CC_PROJECTS"])
        d = projects / "-tmp-limit2-proj"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (d / f"bbbb{i:04d}-0000-0000-0000-000000000000.jsonl").write_text(
                '{"type":"user","message":{"role":"user","content":[{"type":"text",'
                f'"text":"x {i}"}}]}},"cwd":"/tmp/limit2-proj"}}\n',
                encoding="utf-8",
            )
        code, out = _run(["list", "claude", "--limit", "3"])
        self.assertEqual(code, 0)
        self.assertIn("6 sessions, showing 3", out)
        self.assertIn("bbbb0004", out)  # the 3 most recent
        self.assertNotIn("bbbb0000", out)  # the oldest is hidden

    def test_list_search(self):
        code, out = _run(["list", "-s", "OAuth"])
        self.assertEqual(code, 0)
        self.assertIn("cc:00000000", out)
        self.assertIn("codex:019e0000", out)

    def test_list_hides_empty_sessions(self):
        projects = Path(os.environ["CAF_CC_PROJECTS"])
        d = projects / "-tmp-empty-proj"
        d.mkdir(parents=True, exist_ok=True)
        (d / "eeee0000-0000-0000-0000-000000000000.jsonl").write_text(
            '{"type":"queue-operation","operation":"add-context","sessionId":"e"}\n',
            encoding="utf-8",
        )
        code, out = _run(["list", "claude"])
        self.assertEqual(code, 0)
        self.assertNotIn("eeee0000", out)          # empty sessions hidden by default
        self.assertIn("hidden 1 empty sessions", out)
        code_all, out_all = _run(["list", "claude", "--all"])
        self.assertIn("eeee0000", out_all)          # --all shows them

    def test_fork_dry_run(self):
        code, out = _run(["fork", "cc:00000000", "--into", "codex", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Preview:", out)
        self.assertIn("codex resume <new-id>", out)

    def test_fork_at_boundary(self):
        code, out = _run(["fork", "cc:00000000", "--at", "1", "--into", "codex", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("1 user turn / 2 messages", out)  # u1 + a1
        code_before, out_before = _run(
            ["fork", "cc:00000000", "--at", "2", "--before", "--into", "codex", "--dry-run"])
        self.assertEqual(code_before, 0)
        self.assertIn("1 user turn / 2 messages", out_before)  # before 2 = through 1

    def test_fork_at_out_of_range(self):
        code, out = _run(["fork", "cc:00000000", "--at", "99", "--into", "codex", "--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("Error", out)
        self.assertIn("try", out)

    def test_fork_at_zero_rejected(self):
        """--at 0 must error like --at < 0, not silently fork the whole session."""
        code, out = _run(["fork", "cc:00000000", "--at", "0", "--into", "codex", "--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("Invalid fork point", out)

    def test_fork_same_agent_rejected(self):
        """--into with the source agent must be rejected (cross-agent only)."""
        code, out = _run(["fork", "cc:00000000", "--into", "cc"])
        self.assertEqual(code, 1)
        self.assertIn("different", out)

    def test_fork_default_source_deterministic(self):
        """No ref: current-cwd first, then most recent; never the target agent."""
        import caf.cli as cli_mod
        old = cli_mod._stdin_isatty
        cli_mod._stdin_isatty = lambda: False
        try:
            code, out = _run(["fork", "--into", "codex", "--dry-run"])
        finally:
            cli_mod._stdin_isatty = old
        self.assertEqual(code, 0)
        self.assertIn("Preview: cc:00000000", out)  # codex excluded as target -> cc source
        self.assertIn("codex resume <new-id>", out)

    def test_pick_session_rejects_zero_and_out_of_range(self):
        """Interactive picker: 0 must not wrap to the last session."""
        import caf.cli as cli_mod
        from caf.core import CafxError, SessionMeta
        rows = [SessionMeta("cc", "s1", turns=1), SessionMeta("cc", "s2", turns=1)]
        for bad in ("0", "3", "99"):
            with self.assertRaises(CafxError):
                cli_mod._pick_session(rows, bad)
        self.assertEqual(cli_mod._pick_session(rows, "2").session_id, "s2")

    def test_fork_into_alias_excludes_canonical_agent(self):
        """--into claude must exclude agent_id "cc" from source candidates."""
        code, out = _run(["fork", "--into", "claude", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Preview: codex:019e0000", out)  # cc excluded as target -> codex source
        self.assertIn("claude --resume <new-id>", out)

    def test_fork_target_works_without_read_store(self):
        """A freshly installed agent (no read store yet) can still be a fork target."""
        from unittest import mock
        with mock.patch("caf.adapters.claude.shutil.which", return_value="/usr/bin/claude"):
            code, out = _run(
                ["fork", "codex:019e0000", "--into", "claude", "--dry-run"],
                env_overrides={"CAF_CC_PROJECTS": str(Path(self.tmp) / "no-cc-store")},
            )
        self.assertEqual(code, 0)
        self.assertIn("claude --resume <new-id>", out)

    def test_resolve_target_skips_write_unavailable(self):
        """Target candidates must be write_ready; a read-only adapter is not offered."""
        import caf.cli as cli_mod
        from caf.adapters import Adapter
        from caf.core import SessionMeta

        class ReadOnly(Adapter):
            agent_id = "ro"
            def write_ready(self):
                return False

        class Writable(Adapter):
            agent_id = "wr"
            def write_ready(self):
                return True

        src = SessionMeta("cc", "s1")
        target = cli_mod._resolve_target([ReadOnly(), Writable()], src, None)
        self.assertEqual(target.agent_id, "wr")

    def test_fork_unknown_session(self):
        code, out = _run(["fork", "cc:zzzz", "--into", "codex"])
        self.assertEqual(code, 1)
        self.assertIn("Error", out)
        self.assertIn("try", out)

    def test_process_exit_code_nonzero_on_error(self):
        """The CLI process must exit non-zero on errors (not swallow main()'s return code)."""
        import subprocess
        import sys
        proc = subprocess.run(
            [sys.executable, "-m", "caf", "fork", "cc:zzzz", "--into", "codex"],
            capture_output=True, text=True, env=os.environ,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Error", proc.stdout)

    def test_resolve_target_requires_into_non_tty(self):
        """Non-TTY fork with several target agents must fail loudly, never silently pick one."""
        import caf.cli as cli_mod
        from caf.adapters import Adapter
        from caf.core import CafxError, SessionMeta

        class FakeAdapter(Adapter):
            agent_id = "codex"

            def detect(self):
                return True

            def scan_sessions(self):
                return []

        adapters = [FakeAdapter(), type("Dsh", (FakeAdapter,), {"agent_id": "dsh"})()]
        old = cli_mod._stdin_isatty
        cli_mod._stdin_isatty = lambda: False
        try:
            with self.assertRaises(CafxError) as ctx:
                cli_mod._resolve_target(adapters, SessionMeta("cc", "s1"), None)
        finally:
            cli_mod._stdin_isatty = old
        self.assertIn("--into", str(ctx.exception))

    def test_scan_cached_once_per_command(self):
        """One scan per adapter per command: discovery + list + recent-pick reuse the cache."""
        import caf.cli as cli_mod
        from caf.adapters import Adapter
        from caf.core import SessionMeta, pick_recent_session

        class CountingAdapter(Adapter):
            agent_id = "count"
            calls = 0

            def detect(self):
                return True

            def scan_sessions(self):
                CountingAdapter.calls += 1
                return [SessionMeta("count", "c1", title="only", turns=1)]

        adapter = CountingAdapter()
        adapters = [adapter]
        cli_mod._discovery_line(adapters)
        cli_mod._all_sessions(adapters)
        pick_recent_session(adapters)
        self.assertEqual(CountingAdapter.calls, 1)

    def test_doctor_json(self):
        code, out = _run(["doctor", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        agents = {a["agent"] for a in data["agents"]}
        self.assertEqual(agents, {"claude", "codex", "deepseek-harness"})
        status = {a["agent"]: a["read"] for a in data["agents"]}
        self.assertEqual(status, {"claude": "ok", "codex": "ok", "deepseek-harness": "off"})

    def test_install_skill_codex(self):
        """install-skill copies the bundled skill into the agent's skills dir (idempotent)."""
        agents_dir = str(Path(self.tmp) / "agents-skills")
        code, out = _run(["install-skill", "codex"], env_overrides={"CAF_AGENTS_DIR": agents_dir})
        self.assertEqual(code, 0)
        self.assertIn("installed", out)
        dst = Path(agents_dir) / "caf"
        self.assertTrue((dst / "SKILL.md").is_file())
        self.assertTrue((dst / "references" / "list.md").is_file())
        # idempotent reinstall
        code2, _ = _run(["install-skill"], env_overrides={"CAF_AGENTS_DIR": agents_dir})
        self.assertEqual(code2, 0)

    def test_install_skill_unknown_target(self):
        code, out = _run(["install-skill", "gemini"])
        self.assertEqual(code, 1)
        self.assertIn("Unsupported", out)

    def test_output_language_follows_env(self):
        code_zh, out_zh = _run(["list", "claude"], env_overrides={"CAF_LANG": "zh"})
        self.assertEqual(code_zh, 0)
        self.assertIn("会话", out_zh)
        self.assertIn("发现", out_zh)
        code_en, out_en = _run(["list", "claude"], env_overrides={"CAF_LANG": "en"})
        self.assertEqual(code_en, 0)
        self.assertIn("Session", out_en)
        self.assertNotIn("会话", out_en)

    def test_fork_interactive_prefix_selection(self):
        """Interactive mode: id-prefix source pick -> confirm -> dry-run (stdin + isatty injection)."""
        import caf.cli as cli_mod

        feed = io.StringIO("019e0000\n1\n\n")  # source pick, target pick (claude), confirm
        out = io.StringIO()
        old_stdin, old_isatty = sys.stdin, cli_mod._stdin_isatty
        sys.stdin = feed
        cli_mod._stdin_isatty = lambda: True
        try:
            with contextlib.redirect_stdout(out):
                code = cli_mod.main(["fork", "--dry-run"])
        finally:
            sys.stdin = old_stdin
            cli_mod._stdin_isatty = old_isatty
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("Preview: codex:019e0000", text)
        self.assertIn("claude --resume <new-id>", text)


if __name__ == "__main__":
    unittest.main()
