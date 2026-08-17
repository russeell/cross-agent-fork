**English** | [简体中文](README.zh-CN.md)

# cross-agent-fork

> Mid-task in one coding agent, continue in another.

`caf` forks a session from Claude Code, Codex, or DeepSeek Harness into another agent —
the conversation context and working directory come along, and the source session is
never modified.

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

Then just say "fork the current session into Codex" in that agent.

## Quick start

```bash
caf fork                      # interactive picker
caf fork --into codex         # in a project: fork the most recent session here into Codex
caf fork cc:last --into codex # most recent Claude Code session → Codex
caf fork cc:last --at 12 --into codex  # new line from turn 12
```

The source session is never modified. Every fork ends with a paste-ready resume command
for the target agent.

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

`--at N` starts the new line at turn N (everything up to the next user message) —
handy when you want to branch off before things went wrong:

```bash
caf fork cc:last --at 12 --into codex
```

## Extras

- **Agent integration (skills)** — `caf install-skill codex` (or `claude`) installs the
  bundled skill; then just say "fork the current session into Codex" in that agent.

## How it works

The session's text turns and essential tool summaries are replayed into the target
agent's native format: Codex via its official import API, Claude Code and DeepSeek
Harness via thin local envelopes. `caf` keeps no database and no state — it only moves
sessions.

## Limitations

- Text turns and tool summaries are carried; config, permissions, attachments, and git
  state are not migrated.

## Contributing / adding an agent

Adapters are small read/write modules — see [docs/PORTING.md](docs/PORTING.md).

## Non-goals

- No GUI/TUI, no memory layer, no workspace management, no cloud sync
- No same-agent forks (use the agent's native fork), no config migration
- No claims beyond today's three agents — new agents arrive through adapters

## License

MIT
