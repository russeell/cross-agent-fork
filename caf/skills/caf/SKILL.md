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

## Determine the source agent

This skill is agent-neutral: it runs inside any of the supported agents. Always use the
explicit source matching the agent that is running this skill — never an implicit source:

| Agent running this skill | Source ref |
|---|---|
| Claude Code | `cc:last` |
| Codex CLI | `codex:last` |
| DeepSeek Harness | `dsh:last` |

Every supported agent is a first-class fork source and target (`cc <-> codex <-> dsh`);
pick the target with `--into` and let the user choose when they do not.

## Fork

```bash
caf fork <source>:last --into <target>          # e.g. caf fork cc:last --into codex
caf fork <source>:last --at 12 --into <target>  # fork through turn 12
caf list [claude|codex|dsh] [-s keyword] [--all]
caf doctor
```

Bare `caf fork --into <target>` without a source is a terminal convenience (it picks the
most recent session in the current directory, excluding the target agent). Inside an
agent, always name the source explicitly.

## After a fork

Show the two output lines verbatim in a fenced code block; do not summarize, translate,
or reformat them. Explain anything else in the user's language. For a DSH web target,
explain that the command opens the local session list; it is not an exact deep link.
Do not start the target agent unless the user asks.

## Installation & discovery

The skill ships inside the wheel at `caf/skills/caf/SKILL.md`. Install it with the
agent's own skill mechanism, or copy it to the agent's skills directory (Codex:
`~/.agents/skills/caf/`, Claude Code: `~/.claude/skills/caf/`).

| Agent | Skill auto-discovery |
|---|---|
| Claude Code | verified |
| Codex | verified |
| DeepSeek Harness | not yet verified — install manually |

## Notes

- Only run forks the user explicitly asks for; never fork proactively.
- Config/permissions/env are not migrated; the target agent uses its own.
- Show `caf list` output verbatim in a fenced code block. Do not truncate, summarize, or
  convert it into a Markdown table; explain it afterward in the user's language.
