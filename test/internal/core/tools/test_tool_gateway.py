import sys
from unittest.mock import MagicMock

import pytest

from internal.core.tools.tool_gateway import ToolExecutionError, ToolGateway, validate_http_url


def test_validate_http_url_blocks_loopback(monkeypatch):
    monkeypatch.setattr(
        "internal.core.tools.tool_gateway.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(ToolExecutionError, match="私网"):
        validate_http_url("http://localhost/api")


def test_validate_http_url_allows_explicit_host(monkeypatch):
    monkeypatch.setattr("internal.core.tools.tool_gateway._allowed_hosts", lambda: {"localhost"})
    assert validate_http_url("http://localhost/api") == "http://localhost/api"


def test_request_rejects_redirect_to_private_address(monkeypatch):
    monkeypatch.setattr("internal.core.tools.tool_gateway._allowed_hosts", lambda: {"example.com"})
    response = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/admin"})
    monkeypatch.setattr("internal.core.tools.tool_gateway.requests.request", lambda *_args, **_kwargs: response)
    with pytest.raises(ToolExecutionError, match="私网"):
        ToolGateway.request("GET", "https://example.com/start")
    response.close.assert_called_once()


def test_request_strips_credentials_on_cross_origin_redirect(monkeypatch):
    monkeypatch.setattr("internal.core.tools.tool_gateway._allowed_hosts", lambda: {"example.com", "other.com"})
    redirect = MagicMock(status_code=302, headers={"Location": "https://other.com/next"})
    final = MagicMock(status_code=200, headers={}, encoding="utf-8")
    final.iter_content.return_value = [b"ok"]
    request = MagicMock(side_effect=[redirect, final])
    monkeypatch.setattr("internal.core.tools.tool_gateway.requests.request", request)

    result = ToolGateway.request(
        "GET",
        "https://example.com/start",
        headers={"Authorization": "Bearer secret", "X-API-Key": "secret", "X-Test": "keep"},
        params={"token": "secret"},
        cookies={"session": "secret"},
        json={"password": "secret"},
    )
    assert result.text == "ok"
    for key in ("headers", "params", "cookies", "json", "data", "files", "auth"):
        assert key not in request.call_args_list[1].kwargs
    redirect.close.assert_called_once()
    final.close.assert_called_once()


def test_process_timeout_kills_child(tmp_path):
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    result = ToolGateway.process([sys.executable, str(script)], cwd=tmp_path, timeout=1)
    assert result.timed_out is True
    assert result.returncode != 0


def test_skill_runs_in_subprocess_and_returns_json(tmp_path):
    script = tmp_path / "skill.py"
    script.write_text(
        "def run(query):\n    print('log')\n    return f'ok:{query}'\n",
        encoding="utf-8",
    )
    assert ToolGateway.skill(script, "hello", timeout=5) == "ok:hello"


def test_skill_timeout_is_bounded(tmp_path):
    script = tmp_path / "skill.py"
    script.write_text("import time\ndef run(query):\n    time.sleep(5)\n", encoding="utf-8")
    with pytest.raises(ToolExecutionError, match="超时"):
        ToolGateway.skill(script, "hello", timeout=1)
