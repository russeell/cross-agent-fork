# cross-agent-fork 愿景与规划

> 配套：[设计文档](../specs/2026-08-16-cross-agent-fork-design.md)（怎么做）、PORTING.md（怎么扩展）、README.md（怎么用）

## 1. 项目 tree（v0.1 目标形态）

```text
cross-agent-fork/
├── README.md                     ✅ 门面：定位、支持矩阵、快速开始、使用路径
├── LICENSE                       ✅ MIT
├── .gitignore                    ✅
├── pyproject.toml                ⬜ 零运行时依赖（纯 stdlib）
├── caf/
│   ├── __init__.py               ⬜ 版本号（~5 行）
│   ├── __main__.py               ⬜ 入口（~5 行）
│   ├── cli.py                    ⬜ fork/list/doctor + 交互 + 首次汇总（~180 行）
│   ├── core.py                   ⬜ 整会话 IR + 当前会话感知 + 路径探测（~180 行）
│   └── adapters/
│       ├── __init__.py           ⬜ 注册表（~30 行）
│       ├── claude.py             ⬜ 读 CC + 写 CC 信封（~350 行）
│       └── codex.py              ⬜ 读 Codex + 官方 import（~150 行）
├── plugins/
│   └── dsh.py                    ✅ DeepSeek Harness 社区插件（zstd JSONL）
├── skills/
│   └── caf/                      ⬜ SKILL.md + references（markdown，对话即入口）
├── specs/2026-08-16-cross-agent-fork-design.md  ✅ 设计文档
├── docs/
│   ├── PORTING.md                ✅ 新增 agent 适配指南
│   └── VISION.md                 ✅ 愿景与规划（本文件）
└── tests/
    ├── fixtures/                 ⬜ 脱敏样本：cc / codex / 桌面 thread history
    ├── test_core.py              ⬜ ~80 行
    ├── test_adapters.py          ⬜ ~150 行
    └── acceptance/marker_test.sh ⬜ ~40 行
```

代码预算（实测，v0.2）：核心 ~1900 行（cli ~575 + codex ~440 + mcp ~130 + claude ~245 + core ~205
+ plugins/dsh ~285），测试 ~700 行 ≈ **~2900 行（含测试）**。主要超出项：codex 官方导入 JSON-RPC
客户端（~130 行，设计时未预算）与 mcp 服务（~130 行）。

## 2. 最终实现功能

### v0.1（当前设计，~1200 行）

- `caf fork`：整会话 + cwd + 可恢复身份；当前会话感知（零参数）；交互模式；`-c` 复制 / `--json` / `--dry-run`；撤销提示
- `caf list`：统一浏览各 agent 会话（项目过滤、fzf 管道、`--json`）
- `caf doctor`：健康检查 + 每 agent read/write 三档状态（ok / planned / off）+ 版本提示
- `caf skill`：对话即入口（markdown，零代码）
- 首次运行 onboarding、覆盖保护、verify 失败回滚、marker 验收
- 支持：Claude Code ↔ Codex 双向（L1 官方 API + L2 信封）

### v0.2

- 写侧 +opencode、+Gemini CLI
- `--at` 任意边界分叉（opencode before/through 模型）
- `caf tree`（谱系，ASCII / mermaid / html）
- `caf mcp` + skills 插件打包（marketplace 分发）
- `curl | bash` 安装器

### v0.3+

- 写侧 +Cursor；读侧扩展 T2 五家（Grok / Cline / Aider / Kimi / Copilot 的 list/doctor 可见）
- 写侧扩展 T2（v0.4+）；T3 社区驱动（Devin / Factory / Antigravity / Hermes / Pi / Amp）

## 3. 实用性

| 场景 | 用法 | 价值 |
|---|---|---|
| 限流/预算耗尽 | `caf fork cc:last --into codex` | 换 agent 继续，上下文不丢 |
| 正在 A 里干活想换 B | `caf fork --into codex` | 零参数，当前会话自动感知 |
| 死胡同换思路 | v0.2 `--at N` | 在卡住之前分叉 |
| 模型对比 | 同一任务 fork 两条线 | 并行验证 |
| 桌面 ↔ CLI 混用 | v0.2 MCP / v0.1 skill | 对话即入口 |

实用性底线：**从「想 fork」到看到 `→ 继续:` 命令 ≤ 10 秒**；零配置（自动探测）；输出永远是可直接粘贴的 resume 命令。

## 4. 社区痛点（调研证据）

1. **厂商锁定**：CC / Codex / Gemini 会话格式私有、无文档、互不兼容（[Cross-Agent Session Portability](https://codex.danielvaughan.com/2026/06/01/codex-cli-cross-agent-session-portability-continues-casr-handoff/)）
2. **限流/预算切换丢上下文**：ChatGPT Plus / Claude Pro 双订阅用户频繁切换（HN `continues` 讨论）；contextify 作者自述同痛点
3. **转录丢失**：Claude Code 本地转录 30 天默认删除（contextify 产品起点）
4. **手工 workaround 有损**：粘贴摘要丢工具调用历史、exit code、文件修改记录、推理链
5. **双 agent 维护两份上下文**：openai/codex 官方讨论 [#26397](https://github.com/openai/codex/discussions/26397)
6. **会话散落、恢复命令难记**：cc-switch session-manager PRD 的起点（其 ⭐127K 证明受众规模）
7. **工具爆发但互不相通**：2025Q4–2026 出现 10+ 会话工具（casr / opal-bridge / continues / contextify / agentctl / sessionbridge / ctx-switch…），每个都只解决一个角

结论：痛点真实且被多方独立验证；**"跨 agent fork"语义仍无人做**（最接近的 iterm-agent-fork ⭐2 无边界无谱系）。

## 5. 可改进方向

### 近期（v0.2）

- `--at` 任意边界分叉（业界最清晰的 opencode 模型）
- 谱系 `caf tree`（mermaid 让聊天界面原生渲染）
- `caf mcp`：桌面客户端「对话即入口」（opal-bridge 已实证该模式）
- skills 走 plugin marketplace 分发（superpowers 模式）

### 中期（v0.3+）

- `--worktree` 隔离（git 分支语义）
- `--prompt` 继续指令（resume 后目标 agent 直接开工）
- 失败工具调用错误摘要进上下文（死胡同原因要传过去）
- 社区 adapter 生态：PORTING + marker 验收自动化，PR 即可加新 agent

### 长期

- T2/T3 写侧覆盖（Grok / Cline / Aider / Kimi / Copilot…）
- casr 桥接（不承诺；社区明确需要长尾时再评估）
- 插件/桌面市场分发，成为 agent 生态的"标准搬运层"

### 明确不做（反模式）

- TUI / GUI（sessiontree 已满足可视化，我们提供 `--json` 数据）
- 同步镜像（opal-bridge 主场：hooks 自动镜像 + 标题同步）
- 记忆层 / 状态外置（TaskState Vault / PROJECT_CONTEXT.md 主场）
- handoff 文档（continues 主场）
- 全矩阵硬承诺（维护税高，casr 17 provider 仅 104⭐ 是市场答案）

## 一句话定位

> caf = agent 内置 fork 的跨 agent 版：整会话 + cwd + 可恢复身份，主流 agent 集合内任意互通，其余都不管。
