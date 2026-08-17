# doctor workflow

```bash
caf doctor            # health check
caf doctor --json     # machine-readable
```

Shows each agent's read/write status (ok / planned / off), version, store path, and PyPI update hint.

When a fork fails, run doctor first: `off` means the agent is not installed; `planned` means
that direction is not supported yet; if read/write are both `ok`, check login and disk.
