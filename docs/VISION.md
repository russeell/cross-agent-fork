# cross-agent-fork 愿景与边界

> 本文件只回答两个问题：**为什么存在**、**什么坚决不做**。实现细节见 [设计文档](../specs/2026-08-16-cross-agent-fork-design.md)，新增 agent 见 [PORTING.md](PORTING.md)，使用见 [README](../README.md)。

## 一句话定位

> caf = agent 内置 fork 的跨 agent 版：**对话上下文 + cwd + 可恢复的线程身份**，在主流 agent 集合内任意互通，其余都不管。

## 架构不变量

```text
CAF 只有一个会修改状态的动作：fork。
list / doctor / tree 都是只读视图；mcp 只是 transport；plugin 只是 adapter 扩展机制。
CAF 自己不维护数据库、不维护 lineage、不维护 workspace。
CAF owns no sessions. CAF owns no state. CAF only moves sessions.
```

核心概念只有三个：**Session / Adapter / Fork**。i18n、MCP、tree 都只是薄层，不升级成新的领域概念。

## 社区痛点（调研证据）

1. **厂商锁定**：CC / Codex / DSH 会话格式私有、互不兼容
2. **限流/预算切换丢上下文**：双订阅用户频繁切换，手工粘贴摘要有损（丢工具调用历史、exit code、文件修改记录）
3. **会话散落**：`~/.claude/projects/`、`~/.codex/sessions/`、`~/.dsh/sessions/` 各自为政，恢复命令难记
4. **工具爆发但互不相通**：casr / opal-bridge / continues / contextify 等各解决一角，"跨 agent fork"语义仍无人做

## 可改进方向

### 近期（v0.2 已交付）

- `--at` 任意边界分叉、`caf tree`（best-effort 谱系）、`caf mcp`（legacy stdio）、DeepSeek Harness 插件、双语输出

### 中期（v0.3+）

- 写侧扩展：opencode / gemini / cursor（需实机验证）
- 读侧扩展：T2 五家在 list/doctor 可见
- skills marketplace 打包

### 长期

- T3 社区驱动 adapter（Grok / Cline / Aider / Kimi / Copilot…），届时再做 entry-points 级插件分发
- 社区 adapter 生态：PORTING + marker 验收自动化，PR 即可加新 agent

## 明确不做（反模式）

- **TUI/GUI**（提供 `--json` 数据，可视化交给生态）
- **同步镜像 / 记忆层 / 状态外置 / handoff 文档**（各有主场项目）
- **为 tree 建 CAF 自己的 lineage 数据库**（tree 永远 best-effort，读原生元数据）
- **同 agent fork、配置迁移、子代理 fork、云同步**（用原生能力）
- **全矩阵硬承诺**（写侧分级承诺：T1 核心 / T2 计划 / T3 按需）

一句话：**少承诺 > 过度承诺**。真正的挑战不是"还能加什么"，而是"即使看起来有用，也坚决不加什么"。
