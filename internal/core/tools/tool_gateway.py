from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    headers: dict[str, str]
    content: bytes
    text: str
    url: str


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: str
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False


_SAFE_ENV_KEYS = {
    "PATH", "PATHEXT", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "HOME", "USERPROFILE", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV",
}
_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _allowed_hosts() -> set[str]:
    return {
        host.strip().lower()
        for host in os.getenv("TOOL_HTTP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }


def _is_forbidden_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def validate_http_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ToolExecutionError("工具 URL 必须是完整的 http/https 地址")
    host = parts.hostname.lower()
    if host in _allowed_hosts():
        return url
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))}
    except OSError as exc:
        raise ToolExecutionError(f"工具 URL 域名解析失败: {exc}") from exc
    if any(_is_forbidden_ip(address) for address in addresses):
        raise ToolExecutionError("工具 URL 指向私网、环回或保留地址，已拒绝")
    return url


def _kill_process_tree(proc: subprocess.Popen) -> None:
    try:
        import psutil
    except ImportError:
        proc.kill()
        return
    try:
        root = psutil.Process(proc.pid)
        children = root.children(recursive=True)
    except psutil.Error:
        proc.kill()
        return
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        root.kill()
    except psutil.Error:
        pass


class ToolGateway:
    @staticmethod
    def request(
        method: str,
        url: str,
        *,
        timeout: tuple[float, float] = (10, 30),
        max_redirects: int = 5,
        max_bytes: int = 2_000_000,
        **kwargs,
    ) -> HttpResult:
        kwargs.pop("allow_redirects", None)
        kwargs.pop("stream", None)
        current_method = method.upper()
        current_url = validate_http_url(url)
        # shortcut: DNS 校验后仍由 requests 再解析；生产应把工具流量固定到受控出口代理。
        for _ in range(max_redirects + 1):
            response = requests.request(
                current_method,
                current_url,
                allow_redirects=False,
                timeout=timeout,
                stream=True,
                **kwargs,
            )
            try:
                if response.status_code in _REDIRECT_CODES and response.headers.get("Location"):
                    status = response.status_code
                    location = urljoin(current_url, response.headers["Location"])
                    if status == 303 or (status in {301, 302} and current_method == "POST"):
                        current_method = "GET"
                        kwargs.pop("data", None)
                        kwargs.pop("json", None)
                        kwargs.pop("files", None)
                    old_origin = urlsplit(current_url)
                    new_origin = urlsplit(location)
                    if (old_origin.scheme, old_origin.hostname, old_origin.port) != (
                        new_origin.scheme, new_origin.hostname, new_origin.port,
                    ):
                        for key in ("headers", "params", "cookies", "json", "data", "files", "auth"):
                            kwargs.pop(key, None)
                    current_url = validate_http_url(location)
                    continue
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=64_384):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        chunks.append(chunk[: max_bytes - (total - len(chunk))])
                        break
                    chunks.append(chunk)
                content = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                return HttpResult(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=content,
                    text=content.decode(encoding, errors="replace"),
                    url=current_url,
                )
            finally:
                response.close()
        raise ToolExecutionError("工具 URL 重定向次数过多")

    @staticmethod
    def process(
        command: list[str],
        *,
        cwd: Path,
        timeout: int,
        input_text: str | None = None,
        cancel_event: threading.Event | None = None,
        max_output_bytes: int = 1_000_000,
    ) -> ProcessResult:
        env = {key: value for key, value in os.environ.items() if key in _SAFE_ENV_KEYS or key.startswith("TOOL_")}
        env.setdefault("PYTHONPATH", str(Path.cwd()))
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            [str(item) for item in command],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        captured: dict[str, tuple[bytes, bytes]] = {}

        def _communicate() -> None:
            captured["value"] = proc.communicate(input=input_text.encode() if input_text is not None else None)

        reader = threading.Thread(target=_communicate, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        cancelled = False
        while reader.is_alive():
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_process_tree(proc)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _kill_process_tree(proc)
                break
            reader.join(timeout=0.05)
        reader.join(timeout=5)
        stdout, stderr = captured.get("value", (b"", b""))
        output = stdout + stderr
        if len(output) > max_output_bytes:
            output = output[:max_output_bytes] + "\n...[输出已截断]...".encode()
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        return ProcessResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            output=output.decode("utf-8", errors="replace"),
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            cancelled=cancelled,
        )

    @staticmethod
    def skill(script: Path, query: str, *, timeout: int = 60) -> str:
        worker = Path(__file__).with_name("skill_worker.py")
        result = ToolGateway.process(
            [sys.executable, str(worker), str(script)],
            cwd=Path.cwd(),
            timeout=timeout,
            input_text=json.dumps({"query": query}, ensure_ascii=False),
        )
        if result.timed_out:
            raise ToolExecutionError(f"技能执行超时（>{timeout}s）")
        if result.cancelled:
            raise ToolExecutionError("技能执行已取消")
        if result.returncode != 0:
            raise ToolExecutionError(result.output.strip() or "技能执行失败")
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("技能返回了无法解析的结果") from exc
        if not payload.get("ok"):
            raise ToolExecutionError(str(payload.get("error") or "技能执行失败"))
        return str(payload.get("result", ""))
