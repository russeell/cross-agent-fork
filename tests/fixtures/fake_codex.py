#!/usr/bin/env python3
"""Fake codex app-server (stdio JSON-RPC) for testing import success/error/timeout paths.

Usage: FAKE_CODEX_MODE=ok|error|timeout python3 fake_codex.py
"""

import json
import os
import sys
import time

MODE = os.environ.get("FAKE_CODEX_MODE", "ok")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = req.get("method")
    if "id" in req and method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {"codexHome": "/tmp/fake", "userAgent": "fake"},
            }
        )
        continue
    if method == "initialized":
        continue
    if "id" in req and method == "externalAgentConfig/import":
        if MODE == "error":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": req["id"],
                    "error": {"code": -32601, "message": "unknown method"},
                }
            )
            continue
        send({"jsonrpc": "2.0", "id": req["id"], "result": {"importId": "i1"}})
        if MODE == "timeout":
            time.sleep(5)  # Never send completed; let the client time out.
            break
        send(
            {
                "jsonrpc": "2.0",
                "method": "externalAgentConfig/import/completed",
                "params": {
                    "importId": "i1",
                    "itemTypeResults": [
                        {
                            "itemType": "SESSIONS",
                            "successes": [
                                {
                                    "itemType": "SESSIONS",
                                    "cwd": None,
                                    "source": "x.jsonl",
                                    "target": "thread-123",
                                    "title": None,
                                }
                            ],
                            "failures": [],
                        }
                    ],
                },
            }
        )
        continue
