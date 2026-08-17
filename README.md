# cross-agent-fork (caf)

> 跨 agent 会话 fork：在**主流 agent 之间**把整个会话变成另一条可恢复的会话线，继续工作。

支持集合（三档承诺，借鉴 superpowers / agent-reach）：

| Tier | agent | 读侧 | 写侧 |
|---|---|---|---|
| T1 核心 | Claude Code、Codex CLI、**DeepSeek Harness（插件）** | ✅ | ✅ |
| T2 计划 | opencode、Gemini CLI、Cursor | v0.2+ | v0.3+ |
| T3 社区 | Grok、Cline、Aider、Kimi、Copilot… | 按需 | 按需 |

`caf doctor` 显示每个 agent 的 read/write 状态（ok / planned / off），能力边界一目了然。

### DeepSeek Harness 插件

DSH 会话是 zstd 压缩的 JSONL，随插件提供（`caf/plugins/dsh.py`）。启用需 zstd 支持：

```bash
pip install zstandard          # 或 brew install zstd
caf fork cc:last --into dsh    # CC → DSH
caf fork dsh:last --into claude  # DSH → CC
caf fork dsh:last --into codex # DSH → Codex（任意源 → CC 镜像 → 官方导入）
```

内置 fork 是「我从这个点开一条新线」；caf 是「把这条线开到**另一个 agent** 里，原会话不动」。

## 快速开始

```bash
pipx install cross-agent-fork        # 零依赖，秒装
caf fork cc:last --into codex        # 把最近的 Claude Code 会话 fork 进 Codex
caf fork cc:9f3a --at 12 --into codex  # 从第 12 轮开叉（任意轮次）
caf list                             # 统一浏览各 agent 会话
caf doctor                           # 健康检查与修复建议
```

分叉完成后，最后一行永远是**可直接粘贴的恢复命令**：

```text
✓ 分叉: cc:9f3a → codex（整会话，原会话不动）
✓ 写入: codex thread 01J7...（官方导入）
→ 继续: codex resume 01J7...     [-c 复制]
```

## 解决的问题

- 在 Claude Code 里做到一半，想换 Codex 继续——**上下文完整带走**
- 在桌面客户端（Codex Desktop / Claude Code…）里换工具同理——v0.2 起提供 MCP，对话即入口
- 会话散落各处（`~/.claude/projects/`、`~/.codex/sessions/`），找不到、记不住恢复命令

## 使用路径

| 状态 | 用法 |
|---|---|
| 新手/不确定 | `caf fork` — 交互引导，回车可过 |
| 老手/紧急 | `caf fork cc:last --into codex` — 一行完成 |
| 最急（正在 A 里干活） | `caf fork --into codex` — 自动检测当前会话，零参数 |
| 在 agent 里（装 skill 后） | 直接说「把当前会话 fork 到 Codex」— 对话即入口 |

## 在 agent 里使用（skills）

装好 caf 后，把 `skills/caf/` 复制进你的 agent（Codex：`cp -r skills/caf ~/.agents/skills/`），然后直接在对话里说：

> 把当前会话 fork 到 Codex

agent 会自动调用 caf 完成，不需要你记任何会话 id。Claude Code 走 plugin marketplace 打包（v0.2）。

## 设计原则

- **复用优先** — CC→Codex 走官方导入机制（codex-plugin-cc 同款思路），不重复实现格式翻译
- **简洁** — 一个核心动作、两个支撑命令、零运行时依赖
- **优雅** — 唯一的手写格式翻译只有 Codex→CC 写侧（信封翻译，~350 行）
- **实用** — 每个功能对应真实场景，不做演示功能
- **便捷** — 零配置、当前会话感知、交互兜底、输出永远是「可复制的一条命令」

## 架构

```
caf CLI（fork / list / doctor）
├─ core: 整会话 IR · 会话探测
├─ adapters 注册表: 读侧支持所有已安装 agent（list/doctor/源）
├─ claude adapter: 读 CC · 写 CC（文件级信封）
└─ codex adapter: 读 Codex · 写（官方 import API）
```

转换后端：L1 官方 API（cc→codex）+ L2 内置信封（T1 逐个接入 → T2 计划 → T3 社区）。

数据流：

```
caf fork cc:9f3a --into codex
  CC JSONL → 整会话 IR → 官方导入 → codex resume <id>

caf fork codex:01J7 --into cc
  rollout → 整会话 IR → CC 信封写入 → claude --resume <uuid>
```

## Roadmap

- **v0.1**（当前设计）：`fork / list / doctor`；CC↔Codex 双向；整会话；四连测简化为导入/读回验证；回滚；交互模式；caf skill（对话即入口）
- **v0.2**（进行中）：✅ `--at` 任意边界、✅ `caf tree`（谱系）、✅ `caf mcp`（stdio MCP server）；待：skills 插件打包（marketplace）、opencode / gemini 写侧（需实机验证）、`curl | bash` 安装器
- **v0.3**：写侧扩展 cursor；读侧扩展 T2 五家（list/doctor 可见）
- **v0.4+**：写侧扩展 Grok / Cline / Aider / Kimi；T3 社区驱动
- **非目标**：TUI/GUI、同 agent fork（用原生）、子代理 fork、后台会话、配置迁移、云同步

## 参考

设计借鉴：[codex-plugin-cc](https://github.com/openai/codex-plugin-cc)（官方 API 优先 / 整会话 / 一行出口）、[casr](https://github.com/Dicklesworthstone/cross_agent_session_resumer)（原子写 / 读回校验）、[opal-bridge](https://github.com/1va7/opal-bridge)（覆盖保护 / smoke）、[cc-switch](https://github.com/farion1231/cc-switch)（会话管理）、[superpowers](https://github.com/obra/superpowers)（内容与传输分离）、[agent-reach](https://github.com/Panniantong/agent-reach)（doctor）、[anthropics/skills](https://github.com/anthropics/skills)（SKILL.md 结构）。

完整设计见 [`specs/2026-08-16-cross-agent-fork-design.md`](specs/2026-08-16-cross-agent-fork-design.md)，愿景与规划见 [`docs/VISION.md`](docs/VISION.md)，新增 harness 指南见 [`docs/PORTING.md`](docs/PORTING.md)。

## License

MIT
