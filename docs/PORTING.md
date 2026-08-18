# PORTING — adding an agent

CAF's scope is intentionally small: bring native agent fork across boundaries by
creating a new native target session from the source conversation, cwd, and tool evidence.

The boundary is the fork contract, not an agent category: any agent whose sessions
can be reliably expressed as *source session → independent native target session*
qualifies, coding agent or not.

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
2. **Stable snapshot** — the fork reads a bounded point-in-time state of the source at
   time T (`fstat` size first, then read). Core readers are *tail tolerant, interior
   strict*: a mid-append final line is dropped, any malformed interior record fails the
   fork loudly. CC sources bound for the Codex importer are byte-copied; sliced/non-CC
   sources are rendered. The importer/writer never races the source agent.
3. **New target identity** — the write product is a new session, never a rewrite.
4. **Native target resume** — the product must be natively discoverable and resumable.
5. **Same cwd** — the fork carries the source's working directory; never invent one
   (a session with unknown cwd is not forkable).
6. **Exact fork point** — `--at N` forks exactly through turn N; an unfinished turn
   fails loudly instead of silently moving the boundary.
7. **Text preserved** — every text turn inside the boundary is carried over.
8. **Tool call/result evidence preserved** — tool calls and results become portable
   text (name, arguments, output, ok/error when actually observed). Unknown status is
   omitted; never invent success.
9. **No invented state** — write atomically (temp + rename), verify by reading back,
   roll back on failure, and only touch sessions caf itself created. An open tail (last
   turn not durably closed) is never presented as completed: no fabricated `end_turn`,
   `stop_reason`, or `turn/end completed`.
10. **No persistent CAF residue** — temporary bridge files, their `.tmp` leftovers,
    and directories are removed after use (a failed mid-write must not strand a `.tmp`);
    a lone `__caf_bridge__` dir must never make an agent look installed.

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
- **Codex import only accepts CC sources**: every Codex write first builds a stable
  snapshot under `~/.claude/projects/__caf_bridge__/` (byte-copy for untouched CC
  sources, rendered CC envelope otherwise), imports it, then removes the file *and*
  the directory. Claude scans skip `__caf_bridge__` entirely.
