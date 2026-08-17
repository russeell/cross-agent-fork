# cross-agent-fork 设计文档

> 日期：2026-08-17 ｜ 状态：v0.2 定稿（T1 三 agent 六向互通，全部真机验证）｜ 配套：README.md（英文）、README.zh-CN.md（中文）、docs/VISION.md、docs/PORTING.md

## 1. 背景与定位

**问题**：同时使用 Claude Code 和 Codex 的开发者，会话被各自私有格式锁死——在 A 里做到一半，无法在 B 里接着干，只能手工粘贴摘要。

**目标**：在**主流 agent 集合**内实现任意 → 任意 fork：Claude Code ↔ Codex ↔ DeepSeek Harness ↔ opencode ↔ Gemini CLI ↔ Cursor ↔ Grok Build ↔ Cline ↔ Aider ↔ Kimi Code ↔ Copilot CLI（写侧按 Tier 分级承诺，见 §5.1；集合随社区反馈扩展）。

**一句话定位**：caf = agent 内置 fork 的跨 agent 版——**整会话 + cwd + 可恢复的线程身份**，在主流 agent 集合内任意互通，其余都不管。

**现状（v0.2）**：T1 三 agent 六向互通全部打通并真机验证（CC→Codex 走官方导入 API，DSH 为第一个社区插件）；`--at` 任意边界、`caf tree` 谱系、`caf mcp` 桌面入口、双语输出已交付。

**范围**：只做主流/热门 agent；长尾（Kiro、ClawdBot、Vibe 等）不做——需求小、维护税高（casr 支持 17 个 provider 仅 104⭐ 即是证据）。

传播结构（README 与宣传按此顺序）：

1. **换 agent 不丢上下文**——整会话带走
2. **原会话永不动，新线可 resume**
3. **只做会话 fork，不做配置迁移、不做记忆层、不做平台**

**非目标**（明确不做）：工具 schema 保真；配置/权限/环境迁移；子代理/后台 fork；TUI/GUI；同步镜像；handoff 文档；记忆层/状态外置。

### 1.1 竞品位置

codex-plugin-cc 已覆盖「CC→Codex 整会话」（官方导入）。caf 的差异：**独立 CLI**（不依赖 CC 插件环境）+ **Codex→CC 反向**（无官方入口）+ **list/doctor 会话管理** + 未来多 agent。casr/opal-bridge 做多格式转换但无官方导入路径。

极简原则：**有官方 API 就用官方，没有才写信封**。

## 2. 设计原则

1. **复用优先**：有官方 API 用官方（CC→Codex import），没有才自己写信封
2. **简洁**：一个核心动作（fork）+ 两个支撑命令（list/doctor），零运行时依赖
3. **信封翻译**：唯一的手写格式翻译 = Codex→CC 写侧（整会话文本 + 工具摘要行）
4. **实用**：每个功能对应真实场景（限流切换、换思路、双 agent 工作流）
5. **便捷**：零配置、确定性源选择（当前目录优先）、交互兜底、输出以「一条可粘贴命令」结尾

## 3. 核心概念

### 3.1 会话引用 SessionRef

```
<agent>:<id>        # cc:9f3a... / codex:01J7...
cc:last             # 该 agent 最近会话（当前项目）
```

### 3.2 fork 语义

- fork **整个会话**（同 `codex fork` 语义：整会话克隆到新线）
- 源会话**只读**、永不动
- 产物 = 目标 agent 原生可恢复的会话（codex thread / cc jsonl）

### 3.3 fork 内容清单

| 层 | 内容 |
|---|---|
| 保留 | 全部文本轮次（用户/助手）、cwd、可恢复的线程身份 |
| 折叠 | 工具调用 → 摘要行（名称 + 状态 + 文件） |
| 不搬 | 配置（plugins/MCP/hooks/subagents）、权限/环境、附件、子代理、工作区/git 状态 |

理由：与 codex-plugin-cc 一致（它也是 `plugins: []` 全空）；文件系统共享，目标可自读自跑；授权重置是各 agent 的安全设计。

## 4. 命令规范（v0.2 = fork / list / doctor / tree / mcp）

**语言契约**：所有用户可见输出中英双语，`--lang <en|zh>` > `CAF_LANG` > 系统语言；skill 调用时按用户输入语言传 `--lang`。

**输出契约**：`--json` 为机器口；引导行（`-> fork the most recent` 等）只在 TTY 出现，agent/管道/聊天客户端只拿数据；列对齐（id 列 20 宽 + 标题列 36 CJK 感知 + 轮数右对齐）；每个命令输出末尾带「下一步」建议，错误带 `-> try:` 提示。

### 4.1 `caf fork`（核心）

```
caf fork [ref] [--at N] [--through|--before] [--into <agent>] [--dry-run] [-c/--copy] [--json]
```

| 旗标 | 默认 | 说明 |
|---|---|---|
| `ref` | 无 → 确定性规则 | 源会话；无 ref 时：当前 cwd 最新非空会话（排除 `--into` 目标）→ 全局最新 → 交互（仅 TTY）；不依赖进程探测 |
| `--at N` | 最后一个完成轮 | 分叉点（用户消息序号，before/through 模型；`--at 0` 报错） |
| `--through` / `--before` | `--through` | 边界语义（仅与 `--at` 搭配） |
| `--into` | 另一个已装 agent | 目标 agent（唯一时直接用；source == target 报错） |
| `--dry-run` | 关 | 只预览不写入 |
| `-c` / `--copy` | 关 | 复制恢复命令到剪贴板 |
| `--json` | 关 | 机器友好输出 |

**输出**（永远是「✓ 步骤 → 一条可粘贴命令」）：

```text
✓ 分叉: cc:9f3a → codex（整会话，原会话不动）
✓ 写入: codex thread 01J7...（官方导入）
→ 继续: codex resume 01J7...     [-c 复制]
撤销: codex delete 01J7...
```

**交互模式**（无参数时）：

```text
$ caf fork
✓ 发现: Claude Code v2.1.187（12 个会话）+ Codex v0.148.0（9 个会话）
  1. cc:9f3a  OAuth 重构        24 轮  2h ago   ← 当前项目
  2. cc:b7c2  OAuth 重构 (1)    12 轮  1h ago
> 源会话 [1]:
> 目标 agent: [codex]
  将 fork cc:9f3a 整会话 → codex（原会话不动）
  [回车确认 / q 取消]
```

**错误输出**（可操作）：

```text
✗ 未找到会话 codex:9f3a
  → 试试: caf list --all
```

### 4.2 `caf list`

```
caf list [--agent <agent>] [--all] [--json]
```

- 稳定输出契约（gh 模式）：**纯按最近活动排序**（当前项目只标记 `←` 不改序）；默认显示 20 条，`--limit N` / `--all` 显式控制，`-s <关键词>` 标题搜索（cc-switch PRD：搜索是找回会话的主路径）；尾部固定格式提示总数与扩展方式；`--json` 提供完整数据
- 列：agent 前缀、短 id、标题、轮数、时间
- 失败隔离：单 agent 存储损坏不影响整体
- 纯文本行，可管道 `caf list | fzf`；`--json` 输出 SessionMeta（§6.1）

### 4.3 `caf doctor`

健康检查：各 agent 安装状态、存储路径（含桌面 thread history）、版本、read/write 三档状态（ok / planned / off）、修复建议；**只检查本地能力，无联网请求**。fork 失败时跑 `caf doctor` 自诊断。

### 4.4 用户使用方案

三条路径对应三种用户状态：

| 状态 | 用法 | 说明 |
|---|---|---|
| 新手/不确定 | `caf fork` | 交互引导，回车可过 |
| 老手/紧急 | `caf fork cc:last --into codex` | 一行完成 |
| 最急（正在 A 里干活） | `caf fork --into codex` | 当前目录最新会话，零参数 |

首次运行即 onboarding：任何命令首次执行时打印「✓ 发现: Claude Code v2.1.187（12 个会话）+ Codex v0.148.0（9 个会话）」。

## 5. 转换后端（两层，主流集合内互通）

| 层 | 后端 | 覆盖 | 成本 |
|---|---|---|---|
| L1 | 官方 API（external-agent import，同 `/import`、codex-plugin-cc 机制） | CC → Codex | 零翻译，官方维护 |
| L2 | 内置信封（自研 adapter） | claude、codex（v0.1）；opencode、gemini（v0.2）；cursor（v0.3） | 每目标 ~350 行 + 版本维护税 |

路由：按（源, 目标）匹配——L1 优先，其余 L2；`caf doctor` 显示每个 agent 的转换后端状态。

原则：核心零依赖；官方 API 不可用 → 明确报错并提示（升级/登录/`caf doctor`）。casr 桥接**不承诺**（长尾需求小，社区明确需要时再评估）。

### 5.1 Agent 支持矩阵

| Tier | agent | 读侧（list / 源） | 写侧（fork 目标） |
|---|---|---|---|
| **T1 核心**（写侧承诺） | Claude Code、Codex CLI、**DeepSeek Harness（插件）** | ✅ | ✅ |
| **T2 扩展**（写侧计划） | opencode、Gemini CLI、Cursor | v0.2+ | v0.3+ |
| **T3 社区驱动** | Grok、Cline、Aider、Kimi、Copilot、Devin… | 按需 | 按需 |

插件机制：`caf/plugins/` 目录，每模块导出一个 Adapter 子类即被自动发现（零注册代码，插件失败不影响核心）。DSH 为第一个社区插件——格式是 zstd 压缩 JSONL（`~/.dsh/sessions/<projectKey(cwd)>/session-<uuid>/session.jsonl.zstd`），依赖可选（zstandard / zstd CLI）。

借鉴：superpowers 支持列表广（14 harness，每 harness 一个插件清单）；agent-reach 用 doctor 三档状态管理能力边界（ok/warn/off）——**我们的 doctor 显示每个 agent 的 read/write 状态（ok / planned / off）**，支持列表可以广，写侧承诺分级。

## 6. 适配器契约（详见 docs/PORTING.md）

```python
class Adapter:
    agent_id: str                   # 会话引用前缀，如 cc / codex / dsh
    display_name: str               # 展示名，如 claude / codex
    install_hint: str               # 未安装时 doctor 给出的安装提示
    def detect(self) -> bool                    # 是否安装
    def write_ready(self) -> bool               # 写侧是否可用（默认 = 已安装）
    def store_path(self) -> str                 # doctor 展示的实际存储路径
    def store_version(self) -> str              # 未知版本 → 明确报错
    def scan_sessions(self) -> list[SessionMeta]
    def scan_cached(self) -> list[SessionMeta]  # 记忆化扫描：每命令每 adapter 只扫一次
    def invalidate(self) -> None                # 写成功后失效扫描缓存（写后读可见）
    def load_session(self, sid) -> IR           # 整会话（文本轮次 + 工具摘要）
    def project_dir(self, sid) -> str | None
    def resume_command(self, sid, project_dir) -> str
    def write(self, ir) -> str                  # 统一写侧：CC=信封；Codex=官方导入
```

- 路径解析：env override → 默认候选；doctor 声明实际使用路径
- Codex 只读：`session_index.jsonl` → `state_5.sqlite` → rollout glob（三级降级，含桌面 thread history）
- Claude 只读/写：`~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`；信封含 queue-operation 前缀 + parentUuid 链

## 7. 数据格式

### 7.1 SessionMeta（list --json）

```json
{"providerId": "codex", "sessionId": "01J7...", "title": "OAuth 重构",
 "projectDir": "/path", "sourcePath": "…", "createdAt": 0, "lastActiveAt": 0}
```

### 7.2 规范 IR（内部，整会话）

```json
{
  "session": {"agent": "cc", "id": "9f3a...", "projectDir": "/path"},
  "turns": [
    {"seq": 1, "role": "user", "text": "..."},
    {"seq": 2, "role": "assistant", "text": "...",
     "tools": [{"name": "edit_file", "status": "ok", "file": "src/auth.py"}]}
  ]
}
```

## 8. 安全与验收

- 源会话**只读**；CC 写侧原子写（temp + rename）+ `--dry-run`
- verify：CC→Codex = 官方导入返回 threadId（成功即恢复身份）；Codex→CC = 读回校验可解析 + `claude --resume` 可发现
- verify 失败 → **自动回滚**（删除已写文件）；**覆盖保护**：只允许覆盖/删除 caf 自己生成的会话
- **marker 验收**（开发期必跑）：源会话第 3 轮埋暗号 → fork → 目标 resume 提问 → 答对即通过
- 验收标准：从「想 fork」到看到 `→ 继续:` ≤ 10 秒

## 9. 里程碑 0（动代码前，写侧 spike）

1. 官方导入 API：CC JSONL → import → `codex exec resume <id> "…"` 可恢复
2. CC 写侧：手工构造最小 CC JSONL（queue-operation + parentUuid 链）→ `claude --resume <uuid> -p "…"` 可恢复
3. 实测各客户端「当前会话 id 的获取方式」：前台进程探测 + 最近修改会话文件兜底（iterm-agent-fork 模式）
4. 样本脱敏 commit 为 `tests/fixtures/`

## 10. v0.2 候选

- ~~`--at` 任意边界分叉~~ —— 已实现（v0.1.1）：IR 截断 + 镜像桥，所有方向生效
- ~~谱系记录 + `caf tree`~~ —— 已实现（v0.2）：读原生父字段（codex parent_thread_id / dsh parentSession），ASCII + `--json`
- ~~`caf mcp`~~ —— 已实现（v0.2）：stdio JSON-RPC（纯 stdlib），工具 caf_list / caf_fork / caf_tree / caf_doctor
- ~~DeepSeek Harness 插件~~ —— 已实现（v0.2）：首个社区插件（zstd JSONL）
- ~~双语输出~~ —— 已实现（v0.2）：`--lang` / `CAF_LANG` / 系统语言跟随
- ~~命令级扫描缓存~~ —— 已实现（v0.2）：`scan_cached`，每命令每 adapter 只扫一次
- skills 插件打包（marketplace 分发）
- 写侧扩展：opencode / gemini（需实机验证；opencode 存储为版本化 sqlite，写侧走官方 API）
- `--worktree`；`curl | bash` 安装器

## 10.1 v0.3 候选

- **写侧扩展：cursor**（桌面最大群体，信封实现参考 casr 的 cursor provider）
- **读侧扩展：T2 五家**（Grok / Cline / Aider / Kimi / Copilot 的 list/doctor 可见，参考 casr discovery 思路）
- casr 桥接：不承诺，列为未来备选（长尾需求小，社区明确需要时再评估）

## 11. 仓库结构（实测 v0.2，核心 ~2150 行，零运行时依赖）

```
cross-agent-fork/
├── README.md                     # 英文门面：定位、快速开始、使用路径
├── README.zh-CN.md               # 中文版（顶部语言切换）
├── LICENSE                       # MIT
├── pyproject.toml                # 零运行时依赖（纯 stdlib）
├── caf/
│   ├── __init__.py               # 版本号（~3 行）
│   ├── __main__.py               # python -m caf 入口（~4 行）
│   ├── cli.py                    # fork/list/doctor/tree/mcp 命令 + 交互 + 输出契约（~585 行）
│   ├── core.py                   # 整会话 IR + 会话探测 + 引用解析 + 工具函数（~240 行）
│   ├── tree.py                   # 谱系构建 + 渲染（~65 行）
│   ├── _rpc.py                   # stdio JSON-RPC 客户端（~80 行）
│   ├── mcp.py                    # stdio MCP server（~140 行）
│   ├── i18n.py                   # 中英双语（~50 行）
│   └── adapters/
│       ├── __init__.py           # Adapter 契约 + 注册表 + 扫描缓存（~100 行）
│       ├── claude.py             # 读 CC + 写 CC 信封（~250 行）
│       └── codex.py              # 读 Codex + 官方 import（~450 行）
├── caf/plugins/
│   └── dsh.py                    # DeepSeek Harness 社区插件（zstd JSONL，~310 行）
├── skills/
│   └── caf/                      # 英文 SKILL.md + references/（markdown，零代码）
├── specs/2026-08-16-cross-agent-fork-design.md
├── docs/                         # VISION.md（愿景）+ PORTING.md（扩展指南）
└── tests/
    ├── fixtures/                 # 脱敏样本 + fake_codex RPC 模拟器
    ├── test_cli.py / test_core.py / test_adapters.py / test_plugins_dsh.py / test_tree_mcp.py
    └── acceptance/marker_test.sh
```

实测：核心 ~2150 行（含 DSH 插件）、测试 ~800 行、60 个测试全绿；`skills/` 是 markdown，不计入代码量。主要超出项：codex 官方导入 JSON-RPC 客户端与 MCP server（设计时未预算，已拆出 `_rpc.py`/`mcp.py` 独立模块）。

## 12. 使用表面

| 表面 | 形态 | 版本 |
|---|---|---|
| 终端 | CLI 本身（fork/list/doctor/tree） | v0.1 |
| Skills | per-agent SKILL.md，agent 隐式触发「对话即入口」 | v0.1（零代码） |
| MCP | `caf mcp`，桌面/聊天客户端原生调用 | v0.2 ✅ |

Skills 工作流（§12.1 详见）：

1. 用户说「把当前会话 fork 到 X」→ 运行 `caf fork --into X`（当前目录优先自动定位，agent 无需知道 session id）
2. 展示 `→ 继续:` 命令，询问是否执行 resume（不擅自启动目标 agent）
3. 用户问「有哪些会话」→ `caf list`
4. fork 失败 → `caf doctor`

分发：仓库内 `skills/caf/` 随 v0.1 交付；Codex 复制到 `~/.agents/skills/caf`（官方 USER 级位置）；Claude Code 走 marketplace 打包（候选）。

## 13. 参考与借鉴

| 借鉴点 | 来源 |
|---|---|
| 官方 API 优先、整会话、一行出口 | [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) |
| Provider trait × 17 providers、原子写、读回校验 | [casr](https://github.com/Dicklesworthstone/cross_agent_session_resumer) |
| 覆盖保护、smoke 验收 | [opal-bridge](https://github.com/1va7/opal-bridge) |
| SessionMeta、失败隔离、resume 带 cwd | [cc-switch session-manager](https://github.com/farion1231/cc-switch/blob/main/session-manager.md) |
| 零依赖、内容与传输分离、14 harness 分发 | [superpowers](https://github.com/obra/superpowers) |
| doctor 健康检查 | [agent-reach](https://github.com/Panniantong/agent-reach) |
| SKILL.md 结构、隐式触发、渐进披露 | [anthropics/skills](https://github.com/anthropics/skills)、[Codex skills 文档](https://developers.openai.com/codex/skills) |
