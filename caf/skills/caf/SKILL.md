---
name: caf
description: Cross-agent session fork — use when the user wants to switch agents and continue work, fork the current session into another agent (Claude Code <-> Codex <-> DeepSeek Harness), escape rate limits, try a different approach, compare models, list sessions, or check cross-agent tool health. Only fork when the user explicitly asks; never fork proactively.
---

# caf — cross-agent session fork

`caf` turns the session of one agent into a resumable session in another agent; the
original session is never modified.

## When to use

- "fork the current session to Codex / Claude Code", "switch to X and continue",
  "rate-limited, switch tools" -> fork
- "what sessions are there" -> list
- fork failed or "check the environment" -> doctor

## Commands

```bash
caf fork --into <target>          # most recent session in the current directory
caf fork cc:last --into codex     # explicit source
caf fork codex:01J7 --into claude # specific session
caf fork cc:9f3a --at 12 --into codex  # fork through turn 12
caf list [claude|codex|dsh] [-s keyword] [--all]
caf doctor
```

## After a fork

1. Show the output, highlight the final `-> resume:` line.
2. Execute it yourself: an `open http://...` line (dsh web) is safe to run immediately;
   interactive CLI resumes (`claude --resume`, `codex resume`) need the user's go-ahead
   — never start an interactive agent uninvited.
3. Confirm the session shows up.

## Notes

- Only fork sessions the user explicitly asks for; never fork proactively.
- Config/permissions/env are not migrated; the target agent uses its own.
- `caf list` output is a plain-text table; in chat, render it as a Markdown table.
