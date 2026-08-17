---
name: caf
description: Bring native agent fork across agent boundaries — use when the user wants to switch agents and continue work, fork this session into another agent (Claude Code <-> Codex <-> DeepSeek Harness), escape rate limits, try a different approach, compare models, list sessions, or check cross-agent tool health. Only fork when the user explicitly asks; never fork proactively.
---

# caf — native agent fork across boundaries

`caf` brings an agent's native fork workflow across agent boundaries. It creates a
new native session in another agent; the original session is never modified.

## When to use

- "fork this session to Codex / Claude Code", "switch to X and continue",
  "rate-limited, switch tools" -> fork
- "what sessions are there" -> list
- fork failed or "check the environment" -> doctor

## Commands

```bash
# inside an agent, ALWAYS name the source explicitly (your own harness first):
caf fork cc:last --into codex     # inside Claude Code
caf fork codex:last --into claude # inside Codex
caf fork dsh:last --into codex    # inside DeepSeek Harness
caf fork cc:9f3a --at 12 --into codex  # fork through turn 12
caf list [claude|codex|dsh] [-s keyword] [--all]
caf doctor
```

Bare `caf fork --into <target>` is for terminals: it picks the most recent session in
the current directory (excluding the target agent).

## After a fork

Show the result and the final `→ resume:` command to the user. For a DSH web target,
explain that the command opens the local session list; it is not an exact deep link.
Do not start the target agent unless the user asks.

## Notes

- Only run forks the user explicitly asks for; never fork proactively.
- Config/permissions/env are not migrated; the target agent uses its own.
- `caf list` output is a plain-text table; in chat, render it as a Markdown table.
