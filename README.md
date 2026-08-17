**English** | [简体中文](README.zh-CN.md)

# cross-agent-fork

> Bring native agent fork across agent boundaries.

`caf` brings an agent's native fork workflow across agent boundaries. It creates a
new native session in another agent from the source session's conversation, working
directory, and essential tool evidence. The original stays untouched.

Currently supports Claude Code, Codex, and DeepSeek Harness.
Tested on macOS / Linux.

```bash
caf fork cc:last --into codex
```

```text
✓ cc:9f3a → codex
→ codex resume 019...
```

## Install

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

To use caf inside an agent (Codex / Claude Code), install the skill too:

```bash
caf install-skill          # codex (default); or: caf install-skill claude
```

Then just say "fork this session into Codex" in that agent.

## Quick start

```bash
caf fork                      # interactive picker
caf fork --into codex         # in a project: fork the most recent session here into Codex
caf fork cc:last --into codex # most recent Claude Code session → Codex
caf fork cc:last --at 12 --into codex  # fork through turn 12 (turns 1-12 stay in the new session)
```

The source session is never modified. Every fork ends with a paste-ready resume command
for the target agent.

## Switch agents mid-task

The real flow looks like this — you are mid-task in Claude Code and need Codex:

```text
$ caf fork --into codex
✓ cc:9f3a... → codex:019abc...
  source unchanged (24 user turns / 110 messages)
→ codex resume 019abc...

$ codex resume 019abc...
> Continue where we left off.
```

Codex picks up the task — it knows the goal, the files you touched, and what was left
open, without you re-explaining anything. Verified both ways: Claude Code → Codex and
Codex → Claude Code (and into DeepSeek Harness).

## Supported agents

| Agent | Fork from | Fork to |
|---|---|---|
| Claude Code | ✓ | ✓ |
| Codex | ✓ | ✓ |
| DeepSeek Harness | ✓ | ✓ |

## Other commands

```bash
caf list    # browse sessions across agents (-s <keyword> search, --all, --limit N)
caf doctor  # health check: read/write status per agent
```

## Partial fork

`--at N` forks the session through turn N — everything from the start through turn N
is carried into the new session. Handy when you want to branch off before things went
wrong:

```bash
caf fork cc:last --at 12 --into codex
```

## Extras

- **Agent integration (skills)** — `caf install-skill codex` (or `claude`) installs the
  bundled skill; then just say "fork this session into Codex" in that agent.

## How it works

The session's text turns and essential tool evidence are replayed into the target
agent's native format: Codex via its official import API, Claude Code and DeepSeek
Harness via thin local envelopes. `caf` keeps no database and no persistent state —
each fork creates a new native target session and leaves the source untouched.

## Last live-verified

| Direction | Verified |
|---|---|
| Claude Code → Codex | ✅ |
| Codex → Claude Code | ✅ |
| Claude Code → DeepSeek Harness | ✅ |
| Codex → DeepSeek Harness | ✅ |
| DeepSeek Harness → Claude Code | ✅ |
| DeepSeek Harness → Codex | ✅ |

Verified by forking a real mid-task session and resuming in the target agent without
re-explaining the task. Session formats change; these dates are the honest signal:
2026-08-17.

## Limitations

- Text turns and tool evidence are carried; config, permissions, attachments, and git
  state are not migrated.

## Contributing / adding an agent

Adapters are small read/write modules — see [docs/PORTING.md](docs/PORTING.md).

## Non-goals

- No GUI/TUI, no memory layer, no workspace management, no cloud sync
- No same-agent forks (use the agent's native fork), no config migration
- No claims beyond today's three agents — new agents arrive through adapters

## License

MIT
