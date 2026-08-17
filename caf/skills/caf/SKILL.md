---
name: caf
description: Cross-agent session fork — use when the user wants to switch agents and continue work, fork the current session into another agent (Claude Code <-> Codex <-> DeepSeek Harness), escape rate limits, try a different approach, compare models, list sessions, or check cross-agent tool health. Only fork when the user explicitly asks; never fork proactively.
---

# caf — cross-agent session fork

`caf` turns the **entire session** of one agent into a resumable session line in another agent; the original session is never modified.

**Language**: run `caf --lang <en|zh>` matching the user's input language — Chinese input -> `--lang zh` (Chinese output), English input -> `--lang en` (English output). Without a flag, `caf` follows `CAF_LANG` then the system locale.

## When to use

- User says "fork the current session to Codex / Claude Code", "switch to X and continue", "rate-limited, switch tools" -> fork
- User asks "what sessions are there" -> list
- Fork failed or the user asks to check the environment -> doctor

## Workflow

### fork (core)

```bash
caf fork --into <target>          # picks the most recent session in the current directory
caf fork cc:last --into codex     # explicit source
caf fork <agent>:<id> --into cc   # specific session
caf fork cc:9f3a --at 12 --into codex  # fork at turn 12 (arbitrary boundary)
```

After running:

1. Show the output to the user, **highlight the final `→ 继续:` line**
2. Ask the user whether to run resume — **never start the target agent on your own**
3. On confirmation, run `cd <project> && <agent> resume <id>` (or copy it for the user)

### list / doctor

```bash
caf list            # session list
caf doctor          # health check and fix suggestions
```

Full rendering rules: see `references/list.md`, `references/fork.md`, `references/doctor.md`.

## Notes

- Only fork sessions the user explicitly asks for; never fork proactively
- Forking does not migrate config/permissions/env vars — the target agent uses its own
