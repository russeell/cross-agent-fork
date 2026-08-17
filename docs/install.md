# Install cross-agent-fork (caf)

Follow these steps in order. Installing packages modifies the system — the user asked
for this, so proceed.

## 1. Install the CLI

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

If `pipx` is not installed: `brew install pipx` (or `pip install --user pipx`), then
re-run the command. `uv` users can use `uv tool install git+https://github.com/russeell/cross-agent-fork.git`.

## 2. Verify

```bash
caf --version
```

If the command is not found, the tool directory may not be on PATH:
`pipx ensurepath` and open a new shell.

## 3. Install the skill into the current agent

Determine which agent you are running inside, then:

- Codex / Codex CLI → `caf install-skill codex`
- Claude Code → `caf install-skill claude`

## 4. Verify the skill

Confirm the skill file exists:

- Codex: `~/.agents/skills/caf/SKILL.md`
- Claude Code: `~/.claude/skills/caf/SKILL.md`

## Troubleshooting

- Run `caf doctor` — it reports read/write status and install hints per agent.
- Reinstalling is safe: both install steps are idempotent.
