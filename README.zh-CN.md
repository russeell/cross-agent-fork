[English](README.md) | **简体中文**

# cross-agent-fork

> 在一个 coding agent 做到一半，换另一个继续。

`caf` 可以把 Claude Code、Codex 和 DeepSeek Harness 里的会话 fork 到另一个 agent——
对话上下文和工作目录一起带过去，源会话永远不变。

```bash
caf fork cc:last --into codex
```

```text
✓ cc:9f3a → codex
→ codex resume 019...
```

## 安装

```bash
uv tool install cross-agent-fork
```

或：

```bash
pipx install cross-agent-fork
```

## 快速开始

```bash
caf fork                      # 交互选择
caf fork --into codex         # 在当前项目里：把这里最近的会话 fork 到 Codex
caf fork cc:last --into codex # 最近的 Claude Code 会话 → Codex
caf fork cc:last --at 12 --into codex  # 从第 12 轮开一条新线
```

源会话永远不会被修改。每次 fork 结束都会给出一条可直接粘贴的目标 agent 恢复命令。

## 支持

| Agent | 读取 | 写入 |
|---|---:|---:|
| Claude Code | ✓ | ✓ |
| Codex | ✓ | ✓ |
| DeepSeek Harness | ✓ | ✓ |

## 其他命令

```bash
caf list    # 浏览各 agent 会话（-s 关键词搜索 / --all / --limit N）
caf doctor  # 健康检查：每个 agent 的读/写状态
```

## 任意边界分叉

`--at N` 从第 N 轮开新线（包含到下一个用户消息为止的全部内容）——想绕开出问题的部分时很有用：

```bash
caf fork cc:last --at 12 --into codex
```

## 附加能力

- **Agent 集成（skills）** — 把 `skills/caf/` 复制进你的 agent（Codex：`cp -r skills/caf ~/.agents/skills/`），然后直接说"把当前会话 fork 到 Codex"。skill 会按你的输入语言自动传 `--lang`。
- **`caf tree`** — 基于各 agent 原生元数据的 best-effort 跨 agent 谱系。
- **`caf mcp`** — stdio MCP server（legacy 协议），供桌面/聊天客户端调用。

## 工作原理

会话的文本轮次和必要工具摘要会被重放成目标 agent 的原生格式：Codex 走官方导入 API，
Claude Code 和 DeepSeek Harness 走薄信封。`caf` 自己不维护数据库、不维护状态——只搬会话。

## 局限

- 只搬运文本轮次和工具摘要；配置、权限、附件、git 状态不迁移。
- 谱系（`caf tree`）是 best-effort，取决于各目标 agent 保留了哪些元数据。

## 贡献 / 新增 agent

Adapter 是轻量的读写模块——见 [docs/PORTING.md](docs/PORTING.md)。设计细节在
[specs/](specs/)，愿景与边界在 [docs/VISION.md](docs/VISION.md)。

## License

MIT
