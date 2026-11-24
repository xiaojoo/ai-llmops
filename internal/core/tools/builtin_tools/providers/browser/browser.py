#!/usr/bin/env python
"""
@Time    : 2026/3/22 1:18
@Author  : sunxiaojie
@File    : browser.py
"""
# -*- coding: utf-8 -*-
"""
浏览器自动化工具

基于 browser-use + Playwright 实现，让 LangChain Agent 能用自然语言操控浏览器。

进程级单例设计（修复"每次调用/每个子任务都新开一个 Chrome，任务结束浏览器还常驻"）：
- 一个专用工作线程 + 一个事件循环 + 一个 Browser（keep_alive=True 复用），
  同一进程内同一时刻只存在一个 Chrome，所有浏览器任务串行执行；
- 失败/超时后进入退避窗口，窗口内直接拒绝调用，避免 LLM 反复重试重开浏览器；
- 空闲超过 BROWSER_IDLE_TTL 后强制关闭浏览器（session.kill → watchdog 杀进程，
  进程树 psutil 兜底），保证任务结束后浏览器不会常驻。
"""
import asyncio
import atexit
import concurrent.futures
import os
import re
import threading
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from internal.config.settings import get_settings

# ── 配置 ──────────────────────────────────────────────────
# 是否无头模式（Docker/生产环境设为 true，本地调试设为 false 可看到浏览器界面）
_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() != "false"
# 单次任务超时秒数
_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "120"))
# 失败/超时后的退避窗口（秒）：窗口内不再启动浏览器
_BACKOFF = int(os.environ.get("BROWSER_BACKOFF", "60"))
# 空闲回收（秒）：浏览器会话最后一次使用后超过该时长即强制关闭
_IDLE_TTL = int(os.environ.get("BROWSER_IDLE_TTL", "300"))

# 在 URL 与紧随其后的非 ASCII 字符（中文/中文标点）之间补空格。
# browser-use 的 _extract_start_url 用 `https?://[^\s<>"']+` 提取 URL，中文不是空白符，
# 任务写成"登录http://localhost:5173/home页面，使用账号..."时整段会被吞进 URL 导致导航 404。
# 只处理 http(s):// 完整 URL 后紧跟 CJK 的情况，英文空格分隔的正常 URL 不受影响。
_URL_BOUNDARY_RE = re.compile(r"(https?://[^\s<>\"']+?)(?=[^\x00-\x7F])")


def _fix_url_boundary(task: str) -> str:
    return _URL_BOUNDARY_RE.sub(r"\1 ", task)


class BrowserTaskInput(BaseModel):
    task: str = Field(
        description=(
            "要让浏览器执行的任务，用自然语言描述。例如："
            "'打开 https://www.baidu.com 搜索今天的天气并返回结果'、"
            "'访问 https://example.com 填写联系表单，姓名填张三，邮箱填 test@test.com'、"
            "'打开淘宝搜索无线耳机，返回前三条商品的名称和价格'"
        )
    )


class _BrowserWorker:
    """进程级单例浏览器工作线程（ponytail: 全局单锁串行化，浏览器调用本身就是慢操作，吞吐瓶颈可忽略）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None  # browser_use.Browser | None
        self._last_used = 0.0  # 最近一次成功使用时间戳（空闲回收依据）
        self._fail_until = 0.0  # 退避截止时间戳
        self._reaper: threading.Thread | None = None

    # ── 生命周期 ──────────────────────────────────────────
    def _ensure_running(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, daemon=True, name="browser-use-worker",
            )
            self._thread.start()
        if self._reaper is None or not self._reaper.is_alive():
            self._reaper = threading.Thread(
                target=self._reap_idle, daemon=True, name="browser-use-reaper",
            )
            self._reaper.start()

    def shutdown(self) -> None:
        """进程退出前清理：杀掉浏览器并停止工作线程。"""
        with self._lock:
            self._drop_session()
            if self._thread is not None and self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                    self._thread.join(timeout=5)
                except Exception:
                    pass
                self._loop.close()
                self._thread = None
                self._loop = None

    def _reap_idle(self) -> None:
        while True:
            time.sleep(5)
            with self._lock:
                self._reap_once()

    def _reap_once(self) -> None:
        if self._session is not None and time.time() - self._last_used > _IDLE_TTL:
            self._drop_session()

    # ── 执行 ──────────────────────────────────────────────
    def run(self, task: str) -> str:
        self._ensure_running()
        with self._lock:
            if time.time() < self._fail_until:
                wait = int(self._fail_until - time.time())
                return f"[退避] 浏览器任务刚刚失败/超时，请 {wait} 秒后再试，避免重复启动浏览器。"
            try:
                fut = asyncio.run_coroutine_threadsafe(self._run_impl(task), self._loop)
                try:
                    result = fut.result(timeout=_TIMEOUT + 10)
                except concurrent.futures.TimeoutError:
                    fut.cancel()  # 放弃本次执行；已启动的残留由 _drop_session 兜底回收
                    result = f"[超时] 浏览器任务执行超过 {_TIMEOUT + 10} 秒未返回结果，已放弃等待。"
                self._last_used = time.time()
            except Exception as e:
                result = f"[错误] 浏览器任务执行失败：{e}"
            if result.startswith("[超时]") or result.startswith("[错误]"):
                self._fail_until = time.time() + _BACKOFF
                self._drop_session()  # 丢弃可能损坏的会话，下次调用重建（仍只有一个浏览器）
            return result

    async def _run_impl(self, task: str) -> str:
        from browser_use import Agent, Browser
        from browser_use import ChatOpenAI as BrowserChatOpenAI

        # 中文任务里 URL 常与后续文字粘连（"登录http://localhost:5173/home页面…"），
        # browser-use 的起始 URL 提取会把整段当 URL 导航到 404。先补空格分隔。
        task = _fix_url_boundary(task)
        # 视觉识别模型：浏览器操作必须用多模态模型（browser-use 靠截图识别页面元素）。
        # 注意：DeepSeek 等纯文本模型不支持视觉，browser-use 会自动降级为 DOM 文本模式
        # （无截图、每次操作喂整页 DOM 文本）——识别准确度与速度都会大幅下降。
        # browser-use 1.0 使用 Python cell/CDP，保留足够输出预算避免长结果被截断。
        browser_llm = BrowserChatOpenAI(
            model=os.environ.get("BROWSER_LLM_MODEL", "qwen-vl-max"),  # 视觉模型（qwen-vl-max 比 qwen-vl-plus 更准）
            api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            base_url=get_settings().browser_llm_base_url,
        )
        if self._session is None:
            allowed_domains = [
                item.strip() for item in os.environ.get("BROWSER_ALLOWED_DOMAINS", "").split(",")
                if item.strip()
            ]
            if not allowed_domains:
                raise RuntimeError("浏览器工具未配置 BROWSER_ALLOWED_DOMAINS，已拒绝启动")
            self._session = Browser(
                kind="chromium",
                local=True,
                headless=_HEADLESS,
                keep_alive=True,
                allowed_domains=allowed_domains,
                block_ip_addresses=os.environ.get("BROWSER_BLOCK_IP_ADDRESSES", "true").lower() == "true",
            )
        agent = Agent(
            task=task,
            llm=browser_llm,
            browser=self._session,
            judge=False,
            max_context_chars=int(os.environ.get("BROWSER_MAX_CONTEXT_CHARS", "240000")),
            highlight_actions=True,
        )
        try:
            result = await agent.run(timeout=_TIMEOUT)
            final = result.final_result()
            return final if final else "任务已执行完毕，但未返回具体结果。"
        except asyncio.TimeoutError:
            return f"[超时] 浏览器任务执行超过 {_TIMEOUT} 秒，已中断。"

    def _drop_session(self) -> None:
        """强制关闭当前浏览器会话（session.kill → watchdog 杀 Chrome），进程树兜底。"""
        session, self._session = self._session, None
        if session is None or self._loop is None:
            return
        user_data_dir = None
        try:
            user_data_dir = getattr(session, "user_data_dir", None)
            if self._loop is not None and self._loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(session.kill(), self._loop)
                fut.result(timeout=10)
            else:
                asyncio.run(session.kill())
        except Exception:
            pass
        if user_data_dir:
            self._kill_leftover_processes(user_data_dir)

    @staticmethod
    def _kill_leftover_processes(user_data_dir: str) -> None:
        """兜底：session.kill() 失败时按 user-data-dir 强杀残留的 Chrome 进程树。"""
        try:
            import psutil
        except ImportError:
            return
        target = f"--user-data-dir={user_data_dir}"
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if target in cmdline:
                    for child in proc.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    proc.kill()
            except Exception:
                continue


_worker = _BrowserWorker()
atexit.register(_worker.shutdown)


@tool(args_schema=BrowserTaskInput)
def browser(task: str) -> str:
    """
    用自然语言描述任务，让 AI 自动操控浏览器完成网页操作。
    支持：网页浏览、搜索、点击、填写表单、提取数据、截图等。
    任务描述越具体，执行效果越好。
    """
    return _worker.run(task)
