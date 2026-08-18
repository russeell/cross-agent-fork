# cross-agent-fork

[简体中文](README.zh-CN.md)

**Fork a coding-agent session into another agent.**

Claude Code can fork into Claude Code. Codex can fork into Codex.
CAF brings that same fork across agent boundaries.

You're halfway through a task in Claude Code and want to see how Codex would
continue it. Don't summarize the conversation. Don't copy-paste the context.
Fork it:

```bash
caf fork --into codex
```

```text
✓ forked  cc:9f3a → codex:019...
  resume  codex resume 019...
```

Continue in Codex. The source session stays untouched.

**Claude Code ↔ Codex CLI ↔ DeepSeek Harness**

CAF forks the conversation, not your filesystem. The target agent resumes in the
same working directory — CAF does not copy Git or workspace state, and it runs no
daemon, database, or background service.

## Supported agents

| Agent | Ref |
|---|---|
| Claude Code | `cc` |
| Codex CLI | `codex` |
| DeepSeek Harness | `dsh` |

All six cross-agent directions are supported.

## Install

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

Tested on macOS / Linux. Requires Python 3.10+.

## Quick start

```bash
caf fork                          # interactive picker
caf fork --into codex             # fork the most recent session in this directory into Codex
caf fork cc:last --into codex     # most recent Claude Code session → Codex
caf fork cc:last --at 8 --into codex   # branch from an earlier turn
```

`--at N` forks the session through turn N — everything from the start through
turn N is carried into the new session:

```text
turn 1 ── 2 ── 3 ── 4 ── 5 ── ...
                 │
                 └── fork → Codex
```

Every fork ends with a paste-ready resume command for the target agent. The
source session is never modified.

### Utilities

```bash
caf list    # browse sessions across agents (-s <keyword> search, --all, --limit N)
caf doctor  # health check: read/write status per agent
```

## What gets forked

| | Forked? |
|---|---|
| Conversation text | ✓ |
| Tool-call / result evidence | ✓, as readable transcript text |
| Working directory | same path (not copied) |
| Files / Git state | not copied — the target resumes in the same directory |
| Agent config & permissions | no |
| Hidden / internal state | no |

Tool calls and results are carried as readable transcript evidence, not recreated
as native tool events.

## Agent skill

CAF ships a [`SKILL.md`](caf/skills/caf/SKILL.md) so an agent can fork on request
("fork this session into Codex"). Install it with your agent's normal skill
workflow; CAF ships the asset but does not manage host skill installation.

## Verified

Every direction is tested against the real agent CLI (native resume, same cwd,
source untouched, context retained). Unit tests alone are not used to claim
compatibility.

| Direction | Native resume |
|---|---|
| Claude Code → Codex | ✅ |
| Codex → Claude Code | ✅ |
| Claude Code → DeepSeek Harness | ✅ |
| Codex → DeepSeek Harness | ✅ |
| DeepSeek Harness → Claude Code | ✅ |
| DeepSeek Harness → Codex | ✅ |

Last live verification: 2026-08-18.

## Limitations

- Conversation text and tool evidence are carried; agent config, permissions,
  attachments, and hidden state are not.
- Native tool-role semantics are not preserved (a deliberate portability tradeoff).
- Same-agent forks are out of scope — use the agent's native fork.

## Adding an agent

Adapters are small read/write modules — see [docs/PORTING.md](docs/PORTING.md).

## License

MIT
