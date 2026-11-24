from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class RunContext:
    run_id: UUID
    task_id: UUID
    thread_id: str
    namespace: str = ""
    trace_id: str = ""
    traceparent: str = ""

    def config(self, base: dict[str, Any] | None = None) -> dict[str, Any]:
        config = dict(base or {})
        configurable = dict(config.get("configurable") or {})
        configurable["thread_id"] = self.thread_id
        if self.namespace:
            configurable["checkpoint_ns"] = self.namespace
        config["configurable"] = configurable
        metadata = dict(config.get("metadata") or {})
        if self.traceparent:
            metadata["traceparent"] = self.traceparent
        metadata["run_id"] = str(self.run_id)
        config["metadata"] = metadata
        return config

    def child(self, task_id: UUID, namespace: str) -> "RunContext":
        return replace(self, task_id=task_id, namespace=namespace)
