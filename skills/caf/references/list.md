# list workflow

```bash
caf list              # sessions (recent 20 by default, all agents)
caf list --all        # everything
caf list -s <keyword> # title search
caf list --json       # machine-readable (the source of truth for chat rendering)
```

Columns: `Session  Title  Turns  Time` (no row numbers — the CLI prints identifiers
leftmost, gh/kubectl style). After the user picks a session, continue with
`caf fork <agent>:<id> --into <target>`.

**Rendering discipline (chat / desktop clients) — required**:

1. Get the data: `caf list --json` (respect `--agent` / `-s` / `--limit` from the user's request).
2. Render a **complete Markdown table** from that JSON: `Session` = `providerId:sessionId[:12]`,
   `Title`, `Turns` = `turns`, `Time` = relative (`now` / `Xm ago` / `Xh ago`) from `lastActiveAt`.
3. Add **one** short next-step suggestion (`--all` / `--limit N` / `-s keyword`).

Never paste the CLI's plain-text table into chat — its column alignment only holds in
monospaced terminals; chat clients render CJK widths differently. Markdown tables move
alignment to the renderer, so it is always correct. Never summarize or drop rows either.

**Prohibited** (avoid repetition and fabrication):
- Do not restate the session counts (the table and the `共 N 个` line already show them)
- Do not add qualifiers that are not in the output (e.g. "current project" — the list shows all sessions)
- Do not say "verbatim" when you rendered a table — just say "caf list results"
- Keep the suggestion to one sentence; no paragraphs

Note: the CLI's `→ fork 最近的:` / `更多:` guidance lines only appear on a real TTY;
in chat, the agent gives the suggestion itself.
