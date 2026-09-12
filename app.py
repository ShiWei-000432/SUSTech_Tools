#!/usr/bin/env python3
"""启动仅监听本机回环地址的 Web UI。"""

from __future__ import annotations

import threading
import time
from urllib.request import urlopen
import webbrowser

try:
    import uvicorn
    from web_server import app
except ModuleNotFoundError as error:
    raise SystemExit(
        "缺少 Web UI 依赖。请先运行：python3 -m pip install -r requirements.txt"
    ) from error


HOST = "127.0.0.1"
PORT = 8000


def open_browser_when_ready() -> None:
    """仅在本地服务真正响应后打开，避免浏览器指向无效页面。"""

    url = f"http://{HOST}:{PORT}/"
    for _ in range(30):
        try:
            with urlopen(url, timeout=0.5):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.2)


if __name__ == "__main__":
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT)
