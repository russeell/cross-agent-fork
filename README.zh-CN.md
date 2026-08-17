[English](README.md) | **简体中文**

# cross-agent-fork (caf)

> agent 内置 fork 的跨 agent 版：把一个 agent 里的整个会话，变成另一个 agent 里可恢复的会话线——原会话不动。

`caf` 把 A 会话的**全部对话 + 工作目录 + 可恢复的线程身份**，原样变成 B agent 里的原生可恢复会话。在 Claude Code、Codex、DeepSeek Harness 之间切换时，上下文完整带走，不用复制粘贴摘要、不用重新解释。

## 支持矩阵

三档承诺（借鉴 superpowers / agent-reach）：

| Tier | agent | 读侧 | 写侧 |
|---|---|---|---|
| **T1 核心** | Claude Code、Codex CLI、**DeepSeek Harness（插件）** | ✅ | ✅ |
| **T2 计划** | opencode、Gemini CLI、Cursor | v0.2+ | v0.3+ |
| **T3 社区** | Grok、Cline、Aider、Kimi、Copilot… | 按需 | 按需 |

`caf doctor` 显示每个 agent 的 read/write 状态（ok / planned / off），能力边界一目了然。

### DeepSeek Harness 插件

DSH 会话是 zstd 压缩的 JSONL，由首个社区插件（`caf/plugins/dsh.py`）支持。启用需 zstd：

```bash
pip install zstandard          # 或 brew install zstd
caf fork cc:last --into dsh    # Claude Code → DSH
caf fork dsh:last --into claude  # DSH → Claude Code
caf fork dsh:last --into codex # DSH → Codex（任意源 → CC 镜像 → 官方导入）
```

agent 内置的 fork 是在**同一个 agent** 里开新线；`caf` 是把这条线开到**另一个 agent** 里，原会话永不动。

## 快速开始

```bash
pipx install cross-agent-fork        # 零依赖
caf fork cc:last --into codex        # 最近的 Claude Code 会话 → Codex
caf fork cc:9f3a --at 12 --into codex  # 从第 12 轮开叉（任意边界）
caf list                             # 统一浏览各 agent 会话
caf doctor                           # 健康检查与修复建议
```

每次 fork 结束，最后一行永远是**可直接粘贴的恢复命令**：

```text
✓ 分叉: cc:9f3a → codex（整会话，原会话不动）
✓ 写入: codex thread 01J7...（官方导入）
→ 继续: codex resume 01J7...     [-c 复制]
```

## 解决的问题

- 在 Claude Code 里做到一半想换 Codex？**上下文完整带走**。
- 在桌面客户端（Codex Desktop / Claude Code…）里换工具？v0.2 起 `caf mcp` 让任意 MCP 客户端拥有对话级入口。
- 会话散落（`~/.claude/projects/`、`~/.codex/sessions/`、`~/.dsh/sessions/`），找不到、记不住恢复命令？`caf list` 统一呈现。

## 使用路径

| 状态 | 用法 |
|---|---|
| 新手/不确定 | `caf fork` — 交互引导，回车可过 |
| 老手/紧急 | `caf fork cc:last --into codex` — 一行完成 |
| 正在 A 里干活 | `caf fork --into codex` — 自动选当前目录最新会话，零参数 |
| 在 agent 里（装 skill 后） | 「把当前会话 fork 到 Codex」— 对话即入口 |

## 在 agent 里使用（skills）

把 `skills/caf/` 复制进你的 agent（Codex：`cp -r skills/caf ~/.agents/skills/`），然后直接在对话里说：

> 把当前会话 fork 到 Codex

agent 会自动调用 caf 完成，不需要记任何会话 id。skill 指令为英文，并按你的输入语言自动传 `caf --lang`。

## 设计原则

- **复用优先** — CC→Codex 走官方导入机制（codex-plugin-cc 同款思路），不重复实现格式翻译
- **简洁** — 一个核心动作（fork）+ 少量支撑命令，零运行时依赖
- **优雅** — 唯一的手写格式翻译只有 Codex→CC 信封（~250 行）
- **实用** — 每个功能对应真实场景，不做演示功能
- **便捷** — 零配置、确定性源选择（当前目录优先）、交互兜底、输出永远是「可复制的一条命令」

## 架构

```
caf CLI（fork / list / doctor / tree / mcp）
├─ core: 整会话 IR · 确定性源选择（当前目录优先）
├─ adapters 注册表: 读所有已装 agent（list/doctor/源）
├─ claude adapter: 读 CC · 写 CC（文件级信封）
├─ codex adapter: 读 Codex · 写（官方 import API）
├─ plugins/dsh: DeepSeek Harness（zstd JSONL）— 首个社区插件
├─ tree: 跨 agent 谱系 · mcp: stdio MCP server · i18n: 中英双语
```

数据流：

```
caf fork cc:9f3a --into codex
  CC JSONL → 整会话 IR → 官方导入 → codex resume <id>

caf fork codex:01J7 --into cc
  rollout → 整会话 IR → CC 信封写入 → claude --resume <uuid>
```

## Roadmap

- **v0.1** — `fork / list / doctor`；Claude Code ↔ Codex；整会话；回滚；交互模式；caf skill
- **v0.2**（当前）— ✅ `--at` 任意边界、✅ `caf tree` 谱系、✅ `caf mcp`、✅ DeepSeek Harness 插件、✅ 双语输出；下一步：skills marketplace 打包、opencode / gemini 写侧（需实机验证）、`curl | bash` 安装器
- **v0.3** — 写侧：Cursor；读侧：T2 五家在 list/doctor 可见
- **v0.4+** — 写侧：Grok / Cline / Aider / Kimi；T3 社区驱动
- **非目标** — TUI/GUI、同 agent fork（用原生）、子代理 fork、配置迁移、云同步

## 文档

- [设计文档](specs/2026-08-16-cross-agent-fork-design.md) — 定位、语义、适配器契约
- [愿景与规划](docs/VISION.md) — 痛点、社区调研、改进方向
- [PORTING.md](docs/PORTING.md) — 如何新增一个 agent

设计借鉴：[codex-plugin-cc](https://github.com/openai/codex-plugin-cc)、[casr](https://github.com/Dicklesworthstone/cross_agent_session_resumer)、[opal-bridge](https://github.com/1va7/opal-bridge)、[cc-switch](https://github.com/farion1231/cc-switch)、[superpowers](https://github.com/obra/superpowers)、[agent-reach](https://github.com/Panniantong/agent-reach)、[anthropics/skills](https://github.com/anthropics/skills)。

## License

MIT
