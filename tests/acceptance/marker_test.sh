#!/usr/bin/env bash
# marker 验收测试（开发期，需真实 agent 与登录）
# 用法: tests/acceptance/marker_test.sh <src-agent> <target-agent>
# 验证: 源会话第 3 轮埋暗号 → fork → 目标 resume 提问 → 答对即通过
set -euo pipefail

SRC="${1:-claude}"
TARGET="${2:-codex}"
MARKER="MARKER-FOX-42"

echo "== 1. 在源会话埋暗号（手动步骤，先准备一个含暗号的会话）"
echo "   MARKER=$MARKER"

echo "== 2. fork 整会话"
caf fork ${SRC}:last --into ${TARGET} --json

echo "== 3. 用目标 agent 恢复并提问（人工确认）"
echo "   请执行上面输出的 resume 命令，然后提问："
echo "   「上一会话的暗号是？」"
echo ""
echo "== 4. 答对 = 通过（证明上下文跨 agent 保真）"
