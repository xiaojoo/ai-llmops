#!/usr/bin/env python
"""文件系统工具包 —— 服务层：审计日志（AuditLogger）。

每次工具调用写一条 JSONL 到 <workspace>/.agent-audit/fs-audit-YYYYMMDD.jsonl，
供 Agent Trace Viewer 展示：

    Turn 12
     └── Tool: fs_edit
           ├── Path: src/main.py
           ├── Operation: edit
           ├── Lines: 120-135
           ├── Status: Success
           └── Duration: 18ms

条目内容（含 before/after 由 trace 层按需从结果渲染）：
    trace_id / agent_id / tool / operation / path / timestamp / success /
    duration_ms / error_code / extra
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class AuditLogger:
    """JSONL 审计日志记录器（线程安全）"""

    def __init__(self, audit_dir: Path, agent_id: str | None = None):
        self.audit_dir = Path(audit_dir)
        self.agent_id = agent_id or os.environ.get("FILESYSTEM_AGENT_ID", "-")
        self._lock = threading.Lock()

    def log(
        self,
        *,
        tool: str,
        operation: str,
        path: str | None,
        success: bool,
        duration_ms: float,
        error_code: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """写一条审计记录；IO 失败不影响工具结果（best-effort）"""
        try:
            entry = {
                "trace_id": str(uuid4()),
                "agent_id": self.agent_id,
                "tool": tool,
                "operation": operation,
                "path": path or "-",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": success,
                "duration_ms": round(duration_ms, 3),
                "error_code": error_code,
            }
            if extra:
                entry["extra"] = extra

            self.audit_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.audit_dir / f"fs-audit-{datetime.now(timezone.utc):%Y%m%d}.jsonl"
            with self._lock, open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception:  # noqa: S110, BLE001 - 审计失败绝不影响工具本身
            pass
