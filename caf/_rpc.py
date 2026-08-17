"""Minimal stdio JSON-RPC 2.0 client (codex app-server official import)."""

from __future__ import annotations

import json
import select
import time

from caf.core import CafxError
from caf.i18n import t as _t


class RpcClient:
    """Line-delimited JSON-RPC over a subprocess stdio pipe."""

    def __init__(self, proc):
        self.proc = proc

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def call(self, req_id: int, method: str, params: dict, cancel_on: str = "") -> dict:
        """Request/response call; cancel_on = notification that means the call already finished."""
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        for line in self._read_stdout(timeout_s=30):
            obj = json.loads(line)
            if obj.get("id") == req_id:
                if "error" in obj:
                    raise CafxError(_t(f"codex app-server error: {obj['error']}",
                                      f"codex app-server 返回错误: {obj['error']}"))
                return obj.get("result", {})
            if cancel_on and obj.get("method") == cancel_on:
                raise CafxError(_t("codex app-server import completed before request pairing",
                                  "codex app-server 导入提前完成（请求未配对）"))
        raise CafxError(_t("codex app-server did not respond", "codex app-server 无响应"),
                        hint=_t("Check codex install/login with caf doctor", "caf doctor 检查 codex 安装与登录"))

    def wait_for(self, method: str, timeout_s: int) -> dict:
        """Block until a server notification arrives; real timeout via select-polled reads."""
        for line in self._read_stdout(timeout_s):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("method") == method:
                return obj.get("params") or {}
        raise CafxError(_t(f"Timed out waiting for {method}", f"等待 {method} 超时"),
                        hint=_t("Retry or run caf doctor", "重试或运行 caf doctor"))

    def shutdown(self) -> None:
        try:
            self.notify("shutdown")
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    # -- internals

    def _send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read_stdout(self, timeout_s: int):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.5)
            if not ready:
                continue
            line = self.proc.stdout.readline()
            if not line:
                break
            yield line
