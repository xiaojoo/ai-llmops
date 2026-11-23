#!/usr/bin/env python
"""带预算护栏的编排器（借鉴 google/ax 的单机版移植）

google/ax 是跑在 Kubernetes 上的声明式 agent 编排底座（Task/Workspace/Model 三原语 +
沙箱 + 资源限额）。它的 README 里对"为什么要编排器"这句话最实在：

    Agents are a new kind of workload ... and can burn money in a loop if nobody is watching.

本项目不引 ax（它要一套装了 Agent Substrate 的 K8s 集群），只把它最可移植的那一条
——**执行前声明预算、超了就熔断**——落到单机上：

  ax 的 CPU/内存限额 + 集群调度  →  本类的 token / 花费 / 墙钟 / 子任务数四项预算闸门
  ax 的 suspend / resume         →  复用既有 sub_task_checkpoint 断点续跑（不重复实现）
  ax 的 Workspace 预接仓库        →  未移植：要给每个子任务独立工作目录，得改文件系统工具
                                     的 root 解析链路，改动面远超本引擎收益

与 OrchestratorAgent 的关系：完全继承其图结构（plan → confirm_plan → execute → summarize
→ confirm_result）、依赖 DAG 调度、失败自动重规划与断点续跑；只覆写 _budget_allows 一个钩子。
默认引擎仍是 OrchestratorAgent，本类需在应用配置或系统设置里显式选择才生效。
"""
import logging
import os

from internal.core.agent.agents.orchestrator_agent import OrchestratorAgent
from internal.core.agent.entities.agent_entity import AgentState, SubTaskResult

logger = logging.getLogger(__name__)

# 预算项 → 系统设置里的全局默认 env 键。全局把引擎选成 guarded 却不在任何应用里配预算
# 等于没有护栏，所以预算也要能只在系统设置里配一次；应用配置优先于全局默认。
_BUDGET_ENV_KEYS = {
    "max_total_tokens": "ORCHESTRATOR_BUDGET_MAX_TOKENS",
    "max_total_price": "ORCHESTRATOR_BUDGET_MAX_PRICE",
    "max_wall_clock_seconds": "ORCHESTRATOR_BUDGET_MAX_SECONDS",
    "max_dispatched_sub_tasks": "ORCHESTRATOR_BUDGET_MAX_SUBTASKS",
}


class GuardedOrchestratorAgent(OrchestratorAgent):
    """在批次派发前检查预算，超限即熔断剩余子任务（不重规划、不静默继续烧）"""

    def _limit(self, budget: dict, key: str) -> float:
        """应用配置优先，其次系统设置的全局默认；缺省/非法值 = 0 = 该项不限。"""
        raw = budget.get(key)
        if raw in (None, ""):
            raw = os.getenv(_BUDGET_ENV_KEYS[key], "")
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            logger.warning("预算项 %s 取值非法：%r（按不限处理）", key, raw)
            return 0.0

    def _budget_allows(
            self,
            state: AgentState,
            results: dict[int, SubTaskResult],
            elapsed: float = 0.0,
    ) -> tuple[bool, str]:
        budget = (self.agent_config.orchestrator_config or {}).get("budget") or {}
        cap_tokens = int(self._limit(budget, "max_total_tokens"))
        cap_price = self._limit(budget, "max_total_price")
        cap_secs = int(self._limit(budget, "max_wall_clock_seconds"))
        cap_count = int(self._limit(budget, "max_dispatched_sub_tasks"))
        # 一项都没配 = 不限流：宁可放行也不要"忘了配就整轮任务全停"
        if not (cap_tokens or cap_price or cap_secs or cap_count):
            return True, ""

        used_tokens = sum(r.total_token_count or 0 for r in results.values())
        used_price = sum(r.total_price or 0.0 for r in results.values())

        if cap_tokens and used_tokens >= cap_tokens:
            return False, f"预算熔断：已用 {used_tokens} tokens，达上限 {cap_tokens}"
        if cap_price and used_price >= cap_price:
            return False, f"预算熔断：已花费 {used_price:.4f}，达上限 {cap_price:.4f}"
        if cap_secs and elapsed >= cap_secs:
            return False, f"预算熔断：已耗时 {elapsed:.0f}s，达上限 {cap_secs}s"
        if cap_count and len(results) >= cap_count:
            return False, f"预算熔断：已执行 {len(results)} 个子任务，达上限 {cap_count}"
        return True, ""
