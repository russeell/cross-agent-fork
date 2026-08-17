"""Adapter registry: one file per agent, unified read/write contract."""

from __future__ import annotations

from caf.core import CafError, SessionIR, SessionMeta


class Adapter:
    """Adapter contract (see docs/PORTING.md)."""

    agent_id: str = ""  # session-ref prefix, e.g. "cc" / "codex"
    display_name: str = ""  # display name, e.g. "claude" / "codex"
    install_hint: str = ""  # install hint shown by doctor when missing

    def read_ready(self) -> bool:
        """Whether sessions can be read (fork source candidates)."""
        raise NotImplementedError

    def write_ready(self) -> bool:
        """Whether the agent can receive a fork (target candidates)."""
        raise NotImplementedError

    def matches(self, name: str) -> bool:
        """Agent name matching: agent_id ("cc" / "dsh") or display_name ("claude" / "deepseek-harness")."""
        return name in (self.agent_id, self.display_name)

    def store_path(self) -> str:
        """Storage path shown by doctor."""
        return ""

    def store_version(self) -> str:
        return ""

    def scan_sessions(self) -> list[SessionMeta]:
        raise NotImplementedError

    def scan_cached(self) -> list[SessionMeta]:
        """Memoized scan: one scan per adapter per command (adapters are re-instantiated
        per command, so the cache is naturally per-command and never stale)."""
        if getattr(self, "_caf_scan_cache", None) is None:
            self._caf_scan_cache = self.scan_sessions()
        return self._caf_scan_cache

    def load_session(self, sid: str) -> SessionIR:
        raise NotImplementedError

    def resume_command(self, sid: str, project_dir: str | None) -> str:
        raise NotImplementedError

    def write(self, ir: SessionIR) -> str:
        """Write side: official API or file-level envelope; returns the new session id."""
        raise NotImplementedError

    def find_session(self, sid: str) -> SessionMeta | None:
        """Match a session by id prefix; fail loudly when the prefix is ambiguous."""
        matches = [m for m in self.scan_cached() if m.session_id.startswith(sid)]
        if len(matches) > 1:
            raise CafError(
                f"Session prefix {sid} matches {len(matches)} sessions "
                "(threads created in the same millisecond share prefixes)",
                hint="Use a longer prefix, e.g. from caf list --all",
            )
        if matches:
            return matches[0]
        return None


def get_adapter(adapters: list[Adapter], agent_id: str) -> Adapter:
    for adapter in adapters:
        if adapter.matches(agent_id):
            return adapter
    raise CafError(f"Unsupported agent: {agent_id}", hint="caf doctor")


def discover_adapters() -> list[Adapter]:
    """Built-in adapters (claude / codex / dsh), one instance per command."""
    from caf.adapters.claude import ClaudeAdapter
    from caf.adapters.codex import CodexAdapter
    from caf.adapters.dsh import DshAdapter

    return [ClaudeAdapter(), CodexAdapter(), DshAdapter()]
