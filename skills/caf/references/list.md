# list workflow

```bash
caf list              # sessions (recent 20 by default, all agents)
caf list --all        # everything
caf list -s <keyword> # title search
caf list --json       # machine-readable
```

Columns: `# 会话 标题 轮 时间`. After the user picks a session, continue with
`caf fork <agent>:<id> --into <target>`.

**Rendering discipline (chat / desktop clients)**: do not paste raw CLI text and do not
summarize — render the list as a **complete Markdown table** (every visible row in the table),
then add **one** short next-step suggestion (`--all` / `--limit N` / `-s keyword`).
Raw text is fine for real terminals only.

**Prohibited** (avoid repetition and fabrication):
- Do not restate the session counts (the table and the `共 N 个` line already show them)
- Do not add qualifiers that are not in the output (e.g. "current project" — the list shows all sessions)
- Do not say "verbatim" when you rendered a table — just say "caf list results"
- Keep the suggestion to one sentence; no paragraphs

Note: the CLI's `→ fork 最近的:` / `更多:` guidance lines only appear on a real TTY;
in chat, the agent gives the suggestion itself.
