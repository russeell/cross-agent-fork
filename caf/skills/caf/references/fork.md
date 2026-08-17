# fork workflow

## Scenarios and commands

| Scenario | Command |
|---|---|
| Working in the current agent, want to switch | `caf fork --into <target>` (auto-detects the active session) |
| Fork the most recent session | `caf fork cc:last --into codex` |
| Fork a specific session | `caf fork codex:01J7 --into claude` |
| Fork at an arbitrary turn | `caf fork cc:9f3a --at 12 --into codex` |
| Preview without writing | `caf fork cc:last --into codex --dry-run` |
| Copy the resume command | add `-c` |

## Reading the output

```text
Forked: cc:9f3a -> codex (1 user turn / 2 messages, original untouched)
Written: codex 01J7... (official import)

-> resume: codex resume 01J7...
Undo: codex delete 01J7...
```

The `→ 继续:` line is the user's next command. Show it first, ask for confirmation, then run it.

## Failure handling

- `✗ 未找到会话 ... → 试试: caf list --all`: list first, then retry
- `✗ 未找到 codex CLI`: ask the user to install it
- Other failures: run `caf doctor` to diagnose
