# PORTING — 新增 agent 适配指南

> 给 cross-agent-fork 增加一个新 agent（如 opencode）的流程与验收标准。

## 0. 两种加入方式

- **核心 adapter**（`caf/adapters/`）：随主包分发，须保持零运行时依赖
- **社区插件**（`caf/plugins/`）：独立目录，一个模块导出一个 `Adapter` 子类即被自动发现；
  可以有自己的可选依赖（如 DSH 插件的 zstandard），缺失时 `detect()` 返回 False，doctor 给出安装提示

## 1. 写侧策略（先决定，再动手）

| 情况 | 写侧选择 |
|---|---|
| 目标 agent 有官方导入/创建会话 API | 调官方 API（如 Codex external-agent import）——零格式翻译 |
| 目标 agent 无官方入口 | 文件级信封翻译（如 Claude Code JSONL） |

**能复用官方就不自己写格式**（codex-plugin-cc 原则）。

## 2. 不变量（任何 adapter 必须满足）

1. **只读源** — 绝不修改源会话文件
2. **可恢复** — write 产物必须能被目标 agent 原生发现并 resume
3. **整会话** — 全部文本轮次 + 工具摘要行，不裁剪
4. **未知版本即报错** — store 格式版本无法识别时明确报错
5. **覆盖保护** — 只允许覆盖/删除 caf 自己生成的会话

## 3. Adapter 接口

```python
class Adapter:
    agent_id: str                       # "cc" / "codex" / "opencode" ...
    def detect(self) -> bool
    def store_version(self) -> str
    def scan_sessions(self) -> list[SessionMeta]
    def load_session(self, sid) -> IR   # 整会话（文本轮次 + 工具摘要）
    def project_dir(self, sid) -> str | None
    def resume_command(self, sid, project_dir) -> str
    def write(self, ir) -> str          # 官方 API 或文件级信封，返回新会话 id
```

## 4. 流程

1. **探测**：数据目录候选（env override → 默认路径），doctor 声明实际使用路径
2. **只读侧**：scan_sessions + load_session（容忍尾部截断；跳过 isMeta/tool_result 消息）
3. **写侧**：官方 API 优先；文件级则原子写信封（UUID/parentUuid 链、文本轮次 + 工具摘要行）
4. **resume 命令**：模板 + `cd <project_dir> &&` 前缀
5. **验收**：跑 §5 的 marker 测试

## 5. 验收测试（每个新 adapter 必须通过）

```bash
# 1. 在源 agent 会话第 3 轮埋入暗号 MARKER-FOX-42
# 2. caf fork <src> --into <新agent>
# 3. 用目标 agent 的 resume 命令恢复，提问「上一会话的暗号是？」
# 4. 答对 = 通过（证明上下文跨 agent 保真）
```

## 6. 常见陷阱

- **同名不同实**：某 CLI 派生自另一 agent，格式可能「看起来兼容」——用 marker 实测
- **hook 事件 ≠ 会话格式**：插件机制与 session 存储是两回事，分别验证
- **版本漂移**：agent 升级可能改格式（Codex 迁移过 rollout → thread history）——CI 跑 marker 兜底
- **CC 项目目录编码**（实测）：ASCII 字母数字保留，其余每字符 → `-`（中文每字一个 `-`），如
  `/Users/russeell/Documents/开源项目开发/jobfindsme` → `-Users-russeell-Documents--------jobfindsme`；
  decode 有歧义，一律以会话事件里的 `cwd` 字段为准
- **CC resume 按 cwd 限定**：`claude --resume <id>` 必须从会话所属项目目录运行（`cd <project_dir> &&` 前缀不可省），
  否则报 "No conversation found with session ID"
- **Codex 会话文件数 ≠ 会话数**（实测）：本机 196 个 rollout 文件 = 196 个唯一会话，无跨文件会话；
  "0 轮"空会话占多数，交互 fork 只列有轮次的（空会话降噪）
- **Codex threads 表标题可能被审查提示污染**（"The following is the Codex agent history…"）：scan 命中
  污染前缀时回退到首条用户消息（跳过 `<environment_context>` 等注入块）——不要用首条消息当标题的唯一来源
  （CC 侧会引入 `<ide_selection>`、`<command-message>` 新污染，优先 ai-title/summary 事件）
- **DSH 是 zstd 压缩 JSONL**：`~/.dsh/sessions/<projectKey(cwd)>/session-<uuid>/session.jsonl.zstd`；
  projectKey 编码：`/\\:` → `-`（连续折叠）、安全字符保留、其余 `~XXXX`，整体包 `--…--`；
  header 行 `{"type":"session",…}` + 事件行（turn/start、user/message、assistant/message、tool/call、tool/result、turn/end）；
  user/message 的 data 是扁平结构 `{role,content,source}`，tool 结果类的 user 消息以 `source.kind=="tool"` 区分
- **→ codex 的通用桥**：官方导入只接受 CC 源，非 CC 源会先渲染 CC 镜像到
  `~/.claude/projects/__caf_bridge__/` 再导入，用完即删——新 adapter 无需自己实现 codex 写侧
