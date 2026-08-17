**English** | [简体中文](README.zh-CN.md)

# cross-agent-fork

> Bring native agent fork across agent boundaries.

Coding agents can fork sessions, but only into themselves. `caf` brings that primitive
across agent boundaries: the target gets a new native resumable session built from the
source conversation, working directory, and portable tool evidence. The source stays
untouched.

Currently supports Claude Code, Codex, and DeepSeek Harness.
Tested on macOS / Linux.

```bash
caf fork --into codex
```

```text
✓ forked  cc:9f3a → codex:019...
  resume  codex resume 019...
```

## Install

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

The optional agent skill lives in [`caf/skills/caf/`](caf/skills/caf/). CAF ships the
integration asset but does not manage skill installation. You can ask your agent:

```text
Install the caf skill from
https://github.com/russeell/cross-agent-fork/tree/main/caf/skills/caf
using your normal skill installation workflow, then verify that it is available.
```

Then say “fork this session into Codex.” The skill passes `<current-agent>:last`, avoiding
CAF's broader cross-agent source heuristic. Use an explicit session ID when exact identity
is available.

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
✓ forked  cc:9f3a... → codex:019abc...
  resume  codex resume 019abc...

$ codex resume 019abc...
> Continue where we left off.
```

The target receives the portable conversation evidence needed to continue the fork.
What survives is explicit below; CAF does not claim to migrate agent configuration or
hidden runtime state.

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

Verified with real source sessions, native target resume, cwd checks, and continuation
markers. Session formats change; the last live verification was 2026-08-17.

## Limitations

- Text turns and portable tool evidence are carried. Config, permissions, attachments,
  hidden agent state, and git state are not.

## Contributing / adding an agent

Adapters are small read/write modules — see [docs/PORTING.md](docs/PORTING.md).

## Non-goals

- No GUI/TUI, no memory layer, no workspace management, no cloud sync
- No same-agent forks (use the agent's native fork), no config migration
- No claims beyond today's three agents — new agents arrive through adapters

## License

MIT
