#!/usr/bin/env bash
# Fork acceptance test (manual, needs real agents + logins)
# Usage: tests/acceptance/marker_test.sh <src-agent> <target-agent>
# Verifies fork semantics: text AND tool-result markers cross, cwd matches, source unchanged.
set -euo pipefail

SRC="${1:-claude}"
TARGET="${2:-codex}"
TEXT_MARKER="MARKER-FOX-42"
TOOL_MARKER="MARKER-TOOL-7"

echo "== 1. Prepare the source session (manual)"
echo "   a) Ask the agent to create a file tools/marker.txt containing: $TOOL_MARKER"
echo "   b) Then say: my secret is $TEXT_MARKER — remember it."
echo "   The agent's Read of marker.txt is the tool-result carrier."
echo ""
echo "== 2. Fork the whole session"
caf fork ${SRC}:last --into ${TARGET} --json
echo "   -> record the source session hash BEFORE forking and confirm it is unchanged after."
echo ""
echo "== 3. Resume in the target and ask (manual confirmation)"
echo "   Q1: What is my secret?            (expect: $TEXT_MARKER)"
echo "   Q2: What was inside marker.txt?   (expect: $TOOL_MARKER — proves tool results crossed)"
echo "   Q3: What working directory are we in?  (expect: the source cwd)"
echo ""
echo "== 4. Pass = fork semantics survived (text + tool evidence + cwd)."
echo ""
echo "== 5. Verify an exact --at boundary (manual)"
echo "   Prepare a second source session with TEXT_MARKER before turn N and LATE_MARKER after turn N."
echo "   Run: caf fork ${SRC}:last --at N --into ${TARGET} --json"
echo "   Resume the target and confirm TEXT_MARKER is known but LATE_MARKER is unknown."
echo "   An unfinished requested turn must fail; caf must not silently move the boundary."
