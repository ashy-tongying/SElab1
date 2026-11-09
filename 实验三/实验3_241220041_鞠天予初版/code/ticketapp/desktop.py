# -*- coding: utf-8 -*-
"""桌面窗口。双击图标后直接打开活动汇，不先进入浏览器。"""

from __future__ import annotations

import ctypes
import subprocess
import threading
from pathlib import Path

from ticketapp.web import start_server

ICON = Path(__file__).resolve().parent / "webstatic" / "app.ico"
_BROWSERS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
)


def run(db_path=None, port: int = 8765) -> None:
    """打开活动汇窗口。关掉窗口后，这次启动的服务一起退出。"""
    server, chosen, owned = start_server(db_path, port)
    url = f"http://127.0.0.1:{chosen}/login"
    closed = _open_window(url)
    if not owned or server is None:
        return
    if closed:
        server.shutdown()
        server.server_close()
        return
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


def _open_window(url: str) -> bool:
    """用系统窗口显示页面。打不开窗口组件时改用独立应用窗口。"""
    try:
        import webview  # pylint: disable=import-outside-toplevel
    except ImportError:
        _open_app_mode(url)
        return False
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Huodonghui.App")
    webview.create_window(
        "活动汇",
        url,
        width=1280,
        height=820,
        min_size=(1100, 700),
        background_color="#f3efe6",
        text_select=True,
    )
    icon = str(ICON) if ICON.is_file() else None
    webview.start(icon=icon)
    return True


def _open_app_mode(url: str) -> None:
    """弹出没有地址栏的应用窗口。"""
    browser = next((path for path in _BROWSERS if path.is_file()), None)
    if browser is None:
        import webbrowser  # pylint: disable=import-outside-toplevel

        webbrowser.open(url)
        return
    subprocess.Popen(  # pylint: disable=consider-using-with
        [str(browser), f"--app={url}", "--window-size=1280,820"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
