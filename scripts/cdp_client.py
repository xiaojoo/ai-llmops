#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : cdp_client.py

通过 CDP（Chrome DevTools Protocol）控制真实浏览器的轻量客户端。
仅依赖标准库 + websocket-client，用于在沙箱升级后驱动浏览器执行召回测试。
"""
import base64
import json
import time
import urllib.request

import websocket

CDP_HTTP = "http://127.0.0.1:9226"


def get_page_ws(active: bool = True) -> str:
    """获取一个页面目标的 WebSocket 地址（默认活动标签页）"""
    with urllib.request.urlopen(f"{CDP_HTTP}/json", timeout=5) as resp:
        targets = json.loads(resp.read().decode())
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError("没有可用的页面目标")
    pages.sort(key=lambda t: 0 if t.get("url", "").startswith("http://localhost:5173") else 1)
    return pages[0]["webSocketDebuggerUrl"]


class CDP:
    """极简 CDP 客户端：同步发送命令并等待响应"""

    def __init__(self, ws_url: str):
        self._id = 0
        self._ws = websocket.create_connection(ws_url, timeout=30)
        self._pending = {}

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            resp = json.loads(self._ws.recv())
            if resp.get("id") == msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP {method} error: {resp['error']}")
                return resp.get("result", {})
            # 忽略事件消息

    def evaluate(self, expression: str) -> dict:
        """执行 JS，返回 {value} 或异常信息"""
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS error: {result['exceptionDetails']}")
        return result.get("result", {})

    def eval_value(self, expression: str):
        """执行 JS 并返回值"""
        res = self.evaluate(expression)
        return res.get("value")

    def navigate(self, url: str):
        self.send("Page.navigate", {"url": url})

    def screenshot(self, path: str):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["data"]))
        print(f"  [截图] {path}")

    def wait(self, seconds: float):
        time.sleep(seconds)

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass


def new_tab() -> str:
    """打开新标签页，返回其 ws 地址"""
    req = urllib.request.Request(
        f"{CDP_HTTP}/json/new",
        data=b"about:blank",
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        target = json.loads(resp.read().decode())
    return target["webSocketDebuggerUrl"]


if __name__ == "__main__":
    # 冒烟测试
    cdp = CDP(get_page_ws())
    print("browser version:", cdp.eval_value("navigator.userAgent")[:60])
    cdp.close()
