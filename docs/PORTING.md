# PORTING — adding an agent

An adapter is a small read/write module in `caf/adapters/`. Add one file, register it
in `discover_adapters()`, pass the marker test below.

## Adapter contract

```python
class Adapter:
    agent_id: str                   # session-ref prefix: "cc" / "codex" / "dsh"
    display_name: str               # display name: "claude" / "deepseek-harness"
    install_hint: str               # shown by doctor when the agent is missing
    def read_ready(self) -> bool    # fork source candidates (store exists)
    def write_ready(self) -> bool   # fork target candidates (agent can receive a fork)
    def matches(self, name) -> bool # agent_id / display_name alias matching
    def store_path(self) -> str     # shown by doctor
    def store_version(self) -> str  # version, or "" when unknown
    def scan_sessions(self) -> list[SessionMeta]
    def load_session(self, sid) -> SessionIR   # text turns + tool summaries
    def resume_command(self, sid, project_dir) -> str
    def write(self, ir) -> str      # native session, returns the new session id
```

## Write-side strategy

Use the agent's official import API when one exists (Codex: external-agent import).
Otherwise write a thin file-level envelope (Claude Code JSONL, DSH zstd JSONL).

## Invariants

1. Never modify the source session.
2. The write product must be natively discoverable and resumable by the target.
3. Keep all text turns and tool summary lines.
4. Only touch sessions caf itself created (no overwrite of foreign files).
5. Write atomically (temp + rename) and verify by reading back; roll back on failure.

## Acceptance (marker test)

1. Plant a marker phrase in turn 3 of a source-agent session.
2. `caf fork <src> --into <new-agent>`.
3. Resume with the target agent and ask for the marker.
4. A correct answer passes: context survived the crossing.

## Format traps (learned the hard way)

- **CC project-dir encoding**: ASCII alnum kept, every other char becomes `-`
  (one `-` per CJK char). Decoding is ambiguous — always trust the `cwd` field.
- **CC resume is cwd-bound**: `claude --resume` only works from the session's project
  directory (`cd <project> &&` prefix is required).
- **Codex titles can be polluted** by review prompts; fall back to the first user
  message, skipping `<environment_context>` and similar injected blocks.
- **DSH is one zstd frame per JSON line**, checksummed, first frame = header line.
  Message events (`user/message`, `assistant/message`) require `surfaceOp: "append"`
  and a message `id`; `seq` must start at 0 and stay contiguous.
- **Codex import only accepts CC sources**: non-CC sessions are rendered to a CC mirror
  under `~/.claude/projects/__caf_bridge__/`, imported, then deleted.
