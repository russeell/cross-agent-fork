**English** | [简体中文](README.zh-CN.md)

# cross-agent-fork (caf)

> The cross-agent version of your agent's built-in fork: take a whole session from one agent, continue it in another — original untouched.

`caf` carries session A's **conversation history, working directory, and essential tool summaries** into a native, resumable session inside agent B. Switch between Claude Code, Codex, and DeepSeek Harness without re-explaining anything.

## Supported agents

Three-tier commitment (inspired by superpowers / agent-reach):

| Tier | Agent | Read | Write |
|---|---|---|---|
| **T1 core** | Claude Code, Codex CLI, **DeepSeek Harness (plugin)** | ✅ | ✅ |
| **T2 planned** | opencode, Gemini CLI, Cursor | v0.2+ | v0.3+ |
| **T3 community** | Grok, Cline, Aider, Kimi, Copilot… | on demand | on demand |

`caf doctor` shows each agent's read/write status (ok / planned / off), so capability boundaries are always visible.

### DeepSeek Harness plugin

DSH sessions are zstd-compressed JSONL, supported via the first bundled community plugin (`caf/plugins/dsh.py`):

```bash
pipx install "cross-agent-fork[dsh]"   # or: pip install zstandard / brew install zstd
caf fork cc:last --into dsh    # Claude Code → DSH
caf fork dsh:last --into claude  # DSH → Claude Code
caf fork dsh:last --into codex # DSH → Codex (any source → CC mirror → official import)
```

Your agent's built-in fork starts a new line *in the same agent*. `caf` starts that line **in another agent** — the original session never moves.

## Quick start

```bash
pipx install cross-agent-fork        # zero dependencies
caf fork cc:last --into codex        # fork the most recent Claude Code session into Codex
caf fork cc:9f3a --at 12 --into codex  # fork from turn 12 (any boundary)
caf list                             # browse sessions across all agents
caf doctor                           # health check + fix hints
```

Every fork ends with a **paste-ready resume command**:

```text
✓ Forked: cc:9f3a → codex (whole session, original untouched)
✓ Written: codex thread 01J7... (official import)
→ resume: codex resume 01J7...     [-c copy]
```

## What it solves

- Stuck mid-task in Claude Code and want to switch to Codex? **The conversation context comes with you.**
- Working in a desktop client (Codex Desktop, Claude Code, …)? Since v0.2 `caf mcp` gives any MCP client a conversation-level entry point.
- Sessions scattered across `~/.claude/projects/`, `~/.codex/sessions/`, `~/.dsh/sessions/`, impossible to find or resume? `caf list` unifies them.

## Usage paths

| Situation | Command |
|---|---|
| New / unsure | `caf fork` — interactive picker, Enter accepts |
| Experienced / in a hurry | `caf fork cc:last --into codex` — one line |
| In the middle of agent A | `caf fork --into codex` — auto-picks the most recent session in this directory, zero args |
| Inside an agent (with the skill installed) | "fork the current session into Codex" — conversation is the entry point |

## Use it inside your agent (skills)

From a repository checkout, copy `skills/caf/` into your agent (Codex: `cp -r skills/caf ~/.agents/skills/`), then just say:

> Fork the current session into Codex.

The agent calls `caf` for you — no session ids to remember. The skill is English-only and passes your input language to `caf --lang` automatically.

## Design principles

- **Native first** — use official import APIs when available (CC→Codex via the same mechanism as codex-plugin-cc); otherwise keep each adapter's envelope translation thin and local.
- **Minimal** — one core action (fork), a few support commands, zero runtime dependencies.
- **Elegant** — one canonical IR; adapters stay thin readers/writers.
- **Practical** — every feature maps to a real scenario; no demo features.
- **Convenient** — zero config, deterministic source pick (current directory first), interactive fallback, output always ends with a copyable command.

## Architecture

```
caf CLI (fork / list / doctor / tree / mcp)
├─ core: canonical session IR · deterministic source resolution (cwd first)
├─ adapters registry: read all installed agents (list/doctor/source)
├─ claude adapter: read CC · write CC (file-level envelope)
├─ codex adapter: read Codex · write via official import API
├─ plugins/dsh: DeepSeek Harness (zstd JSONL) — first community plugin
├─ tree: best-effort lineage from native metadata · mcp: stdio MCP server (legacy protocol) · i18n: en/zh
```

Data flow:

```
caf fork cc:9f3a --into codex
  CC JSONL → session IR → official import → codex resume <id>

caf fork codex:01J7 --into cc
  rollout → session IR → CC envelope write → claude --resume <uuid>
```

## Roadmap

- **v0.1** — `fork / list / doctor`; Claude Code ↔ Codex; whole session; rollback; interactive mode; caf skill
- **v0.2** (current) — ✅ `--at` boundary forks, ✅ `caf tree` (best-effort lineage), ✅ `caf mcp` (legacy protocol), ✅ DeepSeek Harness plugin, ✅ bilingual output; next: skills marketplace packaging, opencode/Gemini write side (needs real-machine verification), `curl | bash` installer
- **v0.3** — write side: Cursor; read side: T2 agents visible in list/doctor
- **v0.4+** — write side: Grok / Cline / Aider / Kimi; T3 community-driven
- **Non-goals** — TUI/GUI, same-agent forks (use the native one), subagent forks, config migration, cloud sync

## Docs

- [Design doc](specs/2026-08-16-cross-agent-fork-design.md) — positioning, semantics, adapter contract
- [Vision & roadmap](docs/VISION.md) — pain points, community research, improvement directions
- [PORTING.md](docs/PORTING.md) — how to add a new agent

Design references: [codex-plugin-cc](https://github.com/openai/codex-plugin-cc), [casr](https://github.com/Dicklesworthstone/cross_agent_session_resumer), [opal-bridge](https://github.com/1va7/opal-bridge), [cc-switch](https://github.com/farion1231/cc-switch), [superpowers](https://github.com/obra/superpowers), [agent-reach](https://github.com/Panniantong/agent-reach), [anthropics/skills](https://github.com/anthropics/skills).

## License

MIT
