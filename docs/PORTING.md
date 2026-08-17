# PORTING — adding an agent

CAF's scope is intentionally small: bring native agent fork across boundaries by
creating a new native target session from the source conversation, cwd, and tool evidence.

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
    def load_session(self, sid) -> ForkSnapshot   # text turns containing portable evidence
    def resume_command(self, sid, project_dir) -> str
    def write(self, ir) -> str      # native session, returns the new session id
```

## Write-side strategy

Use the agent's official import API when one exists (Codex: external-agent import).
Otherwise write a thin file-level envelope (Claude Code JSONL, DSH zstd JSONL).

## Fork contract

Every adapter must honor the fork semantics, not just the file format:

1. **Source immutable** — never modify the source session.
2. **New target identity** — the write product is a new session, never a rewrite.
3. **Native target resume** — the product must be natively discoverable and resumable.
4. **Same cwd** — the fork carries the source's working directory; never invent one
   (a session with unknown cwd is not forkable).
5. **Exact fork point** — `--at N` forks exactly through turn N; an unfinished turn
   fails loudly instead of silently moving the boundary.
6. **Portable evidence preserved** — readers turn tool calls/results into portable text.
   Unknown status is omitted; only an observed result is marked `ok` or `error`.
7. **No invented state** — write atomically (temp + rename), verify by reading back,
   roll back on failure, and only touch sessions caf itself created.

## Acceptance (marker test)

Plant two markers in a source-agent session:

- `TEXT_MARKER` in a user message
- `TOOL_MARKER` inside a tool result (e.g. have the agent read a file containing it)

Then:

1. `caf fork <src> --into <new-agent>` — target must know `TEXT_MARKER` **and**
   `TOOL_MARKER`, and the cwd must match the source.
2. The source session hash is unchanged.
3. `caf fork <src> --at N` — target knows markers before N and nothing after
   (a `LATE_MARKER` placed after N must be unknown).

A correct answer means the fork (not just the parser) survived.

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
