[English](README.md) | **简体中文**

# cross-agent-fork

> 把 Agent 内置的 session fork 扩展到不同 Agent 之间。

`caf` 可以把 Claude Code、Codex 和 DeepSeek Harness 里的会话 fork 到另一个 agent——
对话上下文和工作目录一起带过去。原会话不动，新会话从同一上下文继续。

当前支持 Claude Code、Codex、DeepSeek Harness。
已在 macOS / Linux 验证。

```bash
caf fork cc:last --into codex
```

```text
✓ cc:9f3a → codex
→ codex resume 019...
```

## 安装

```bash
pipx install git+https://github.com/russeell/cross-agent-fork.git
```

想在 agent（Codex / Claude Code）里用 caf，再装 skill：

```bash
caf install-skill          # codex（默认）；或: caf install-skill claude
```

装完后直接说"把当前会话 fork 到 Codex"即可。

## 快速开始

```bash
caf fork                      # 交互选择
caf fork --into codex         # 在当前项目里：把这里最近的会话 fork 到 Codex
caf fork cc:last --into codex # 最近的 Claude Code 会话 → Codex
caf fork cc:last --at 12 --into codex  # 从第 12 轮结束处 fork（前 1~12 轮全部保留）
```

源会话永远不会被修改。每次 fork 结束都会给出一条可直接粘贴的目标 agent 恢复命令。

## 做到一半换 agent

真实流程是这样的——你在 Claude Code 里做到一半，想换到 Codex：

```text
$ caf fork --into codex
✓ cc:9f3a... → codex:019abc...
  source unchanged（24 轮 / 110 条消息，原会话不动）
→ codex resume 019abc...

$ codex resume 019abc...
> 继续刚才的任务。
```

Codex 会直接接上——它知道目标、你改过的文件、还有哪些没做完，不需要你重新解释。
双向真实验证过：Claude Code → Codex 和 Codex → Claude Code（以及 → DeepSeek Harness）。

## 支持

| Agent | Fork from | Fork to |
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

`--at N` 从第 N 轮结束处 fork，新会话保留此前全部上下文——想绕开出问题的部分时很有用：

```bash
caf fork cc:last --at 12 --into codex
```

## 附加能力

- **Agent 集成（skills）** — `caf install-skill codex`（或 `claude`）自动安装随包携带的 skill；装完后直接说"把当前会话 fork 到 Codex"即可。

## 工作原理

会话的文本轮次和必要工具证据会被重放成目标 agent 的原生格式：Codex 走官方导入 API，
Claude Code 和 DeepSeek Harness 走薄信封。`caf` 不维护数据库或持久状态——每次 fork
只创建一个新的目标原生会话，源会话保持不变。

## 真机验证记录

| 方向 | 验证 |
|---|---|
| Claude Code → Codex | ✅ |
| Codex → Claude Code | ✅ |
| Claude Code → DeepSeek Harness | ✅ |
| Codex → DeepSeek Harness | ✅ |
| DeepSeek Harness → Claude Code | ✅ |
| DeepSeek Harness → Codex | ✅ |

验证方式：fork 真实进行中的会话，在目标 agent resume 后不重新解释任务即可继续。
Agent 会话格式会变化，日期才是最诚实的信号：2026-08-17。

## 局限

- 只搬运文本轮次和工具证据；配置、权限、附件、git 状态不迁移。

## 贡献 / 新增 agent

Adapter 是轻量的读写模块——见 [docs/PORTING.md](docs/PORTING.md)。

## 非目标

- 不做 GUI/TUI、记忆层、工作区管理、云同步
- 不做同 agent fork（用原生）、配置迁移
- 不承诺今天三个 agent 之外的能力——新 agent 通过 adapter 加入

## License

MIT
