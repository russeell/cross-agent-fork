[English](README.md) | **简体中文**

# cross-agent-fork

> 把 Agent 内置 fork 带到不同 Agent 之间。

Coding Agent 的内置 fork 通常只能 fork 给自己。`caf` 把这个 primitive 带到 Agent
边界之外：基于源对话、工作目录和可移植工具证据，在目标 Agent 中创建一个新的原生
可恢复会话。源会话保持不变。

当前支持 Claude Code、Codex 和 DeepSeek Harness。
已在 macOS / Linux 验证。

```bash
caf fork --into codex
```

```text
✓ forked  cc:9f3a → codex:019...
  resume  codex resume 019...
```

## 安装

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

可选的 Agent skill 位于 [`caf/skills/caf/`](caf/skills/caf/)。CAF 只提供集成文件，
不负责管理 skill 的安装生命周期。可以直接对 Agent 说：

```text
请从 https://github.com/russeell/cross-agent-fork/tree/main/caf/skills/caf
读取并按你原生的 skill 安装方式安装 caf skill，然后确认它可用。
```

装完后直接说“把这个会话 fork 到 Codex”。skill 会传入 `<当前 Agent>:last`，避免
CAF 在多个 Agent 之间猜源；如果能拿到精确 session ID，就应直接使用 ID。

## 快速开始

```bash
caf fork                      # 交互选择
caf fork --into codex         # 当前项目中最近的会话 → Codex
caf fork cc:last --into codex # 最近的 Claude Code 会话 → Codex
caf fork cc:last --at 12 --into codex  # 从第 12 轮结束处 fork
```

源会话永远不会被修改。每次 fork 结束都会给出一条可直接粘贴的目标 Agent 恢复命令。

## 做到一半换 Agent

你在 Claude Code 里做到一半，想切到 Codex：

```text
$ caf fork --into codex
✓ forked  cc:9f3a... → codex:019abc...
  resume  codex resume 019abc...

$ codex resume 019abc...
> 继续刚才的任务。
```

目标 Agent 会得到继续这个 fork 所需的可移植对话证据。具体保留范围见下文；CAF
不承诺迁移 Agent 配置或隐藏运行状态。

## 支持的 Agent

| Agent | Fork from | Fork to |
|---|---|---|
| Claude Code | ✓ | ✓ |
| Codex | ✓ | ✓ |
| DeepSeek Harness | ✓ | ✓ |

## 其他命令

```bash
caf list    # 浏览各 Agent 会话（-s 关键词搜索 / --all / --limit N）
caf doctor  # 检查每个 Agent 的读写状态
```

## 从指定轮次 fork

`--at N` 会精确 fork 到第 N 个用户轮次结束处，新会话只保留从开头到该轮的内容。
如果第 N 轮尚未完成，CAF 会明确报错，不会悄悄退回上一轮。

```bash
caf fork cc:last --at 12 --into codex
```

## 工作原理

Reader 将文本轮次和工具调用/结果转换成可移植文本证据，再由目标 Adapter 写成原生
可恢复格式：Codex 使用官方导入 API，Claude Code 和 DeepSeek Harness 使用轻量本地
信封。`caf` 不维护数据库或持久状态；每次 fork 创建新的目标会话，源会话保持不变。

## 最近一次真机验证

| 方向 | 验证 |
|---|---|
| Claude Code → Codex | ✅ |
| Codex → Claude Code | ✅ |
| Claude Code → DeepSeek Harness | ✅ |
| Codex → DeepSeek Harness | ✅ |
| DeepSeek Harness → Claude Code | ✅ |
| DeepSeek Harness → Codex | ✅ |

验证包括真实源会话、目标 Agent 原生 resume、cwd 检查和上下文 marker。
Agent 会话格式会变化，最近一次真机验证日期为 2026-08-17。

## 局限

- 保留文本轮次和可移植工具证据；配置、权限、附件、隐藏 Agent 状态和 git 状态不保留。

## 贡献 / 新增 Agent

Adapter 是轻量读写模块，参见 [docs/PORTING.md](docs/PORTING.md)。

## 非目标

- 不做 GUI/TUI、记忆层、工作区管理或云同步
- 不做同 Agent fork（使用 Agent 原生 fork），不迁移配置
- 不承诺当前三个 Agent 之外的能力；新 Agent 通过 Adapter 加入

## License

MIT
