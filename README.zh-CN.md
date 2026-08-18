# cross-agent-fork

[English](README.md)

**把 Coding Agent 的会话 fork 到另一个 Agent。**

Claude Code 只能 fork 给 Claude Code，Codex 只能 fork 给 Codex。
CAF 把同样的 fork 带到 Agent 边界之外。

你在 Claude Code 里做到一半，想看看 Codex 会怎么继续。
不用总结对话，不用复制粘贴上下文。Fork 它：

```bash
caf fork --into codex
```

```text
✓ forked  cc:9f3a → codex:019...
  resume  codex resume 019...
```

在 Codex 里继续。源会话保持不变。

**Claude Code ↔ Codex CLI ↔ DeepSeek Harness**

CAF fork 的是对话，不是你的文件系统。目标 Agent 在**同一个工作目录**里恢复——
CAF 不复制 Git 或工作区状态，也不运行任何 daemon、数据库或后台服务。

## 支持的 Agent

| Agent | Ref |
|---|---|
| Claude Code | `cc` |
| Codex CLI | `codex` |
| DeepSeek Harness | `dsh` |

六个跨 Agent 方向全部支持。

## 安装

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

已在 macOS / Linux 验证。需要 Python 3.10+。

## 快速开始

```bash
caf fork                          # 交互选择
caf fork --into codex             # 把当前目录最近的会话 fork 到 Codex
caf fork cc:last --into codex     # 最近的 Claude Code 会话 → Codex
caf fork cc:last --at 8 --into codex   # 从更早的轮次分叉
```

`--at N` 从第 N 轮处 fork——从开头到第 N 轮的内容都会带进新会话：

```text
turn 1 ── 2 ── 3 ── 4 ── 5 ── ...
                 │
                 └── fork → Codex
```

每次 fork 都以一条可直接粘贴的目标 Agent 恢复命令结束。源会话永远不会被修改。

### 辅助命令

```bash
caf list    # 浏览各 Agent 的会话（-s <关键词> 搜索、--all、--limit N）
caf doctor  # 健康检查：各 Agent 的读取/写入状态
```

## Fork 带走了什么

| | 是否带过去 |
|---|---|
| 对话文本 | ✓ |
| 工具调用/结果证据 | ✓，以可读的转录文本形式 |
| 工作目录 | 同一路径（不复制） |
| 文件 / Git 状态 | 不复制——目标在同一个目录里恢复 |
| Agent 配置与权限 | 否 |
| 隐藏/内部状态 | 否 |

工具调用和结果以可读的转录文本证据携带，不会重新生成为原生工具事件。

## Agent Skill

CAF 自带一份 [`SKILL.md`](caf/skills/caf/SKILL.md)，让 Agent 可以按请求执行 fork
（"fork this session into Codex"）。用你所用 Agent 的常规 skill 安装流程安装；
CAF 提供资产，但不管理宿主 skill 的安装。

## 验证

每个方向都用真实 Agent CLI 测试过（原生恢复、同一 cwd、源不变、上下文保留）。
不只用单元测试声称兼容。

| 方向 | 原生恢复 |
|---|---|
| Claude Code → Codex | ✅ |
| Codex → Claude Code | ✅ |
| Claude Code → DeepSeek Harness | ✅ |
| Codex → DeepSeek Harness | ✅ |
| DeepSeek Harness → Claude Code | ✅ |
| DeepSeek Harness → Codex | ✅ |

最近一次真机验证：2026-08-18。

## 限制

- 携带对话文本和工具证据；Agent 配置、权限、附件和隐藏状态不携带。
- 不保留原生工具角色语义（有意的可移植性取舍）。
- 同 Agent fork 不在范围内——请使用 Agent 原生 fork。

## 添加 Agent

Adapter 是小的读写模块——见 [docs/PORTING.md](docs/PORTING.md)。

## License

MIT
