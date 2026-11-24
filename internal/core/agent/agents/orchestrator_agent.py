#!/usr/bin/env python
"""编排器智能体：任务分解 → 任务分配确认 → 并行子Agent执行 → 汇总 → 汇总确认

图结构：plan → (confirm_plan → (execute → (失败自动重拆→plan | summarize → confirm_result)) | direct_answer) → END
确认点 1（confirm_plan→_replan_condition）：任务分配方案确认，重新规划回 plan；
确认点 2（confirm_result→_confirm_done_condition）：汇总结果歧义确认，重新生成回 plan。
自动重规划（execute→_execute_condition）：子任务 error/timeout 时不经确认框直接回 plan 重拆。
子任务按 depends_on 分批调度（同批并行、批间串行），前置产出注入后置子任务的提问。
子 Agent 事件通过 AgentQueueManager.forward 桥接进主队列（带 sub_task_id/sub_task_title）。
断点保存/恢复在 _run_subtask 中实现。
"""
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, messages_to_dict
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.agents.base_agent import BaseAgent, is_length_overflow_error
from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.agents.react_agent import ReACTAgent
from internal.core.agent.entities.agent_entity import (
    ASK_USER_TOOL_NAME,
    ASK_USER_WAIT_TIMEOUT,
    ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE,
    ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE,
    AgentConfig,
    AgentState,
    ConfirmVerdict,
    SubTaskPlanInput,
    SubTaskResult,
    SubTaskSpec,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature, build_structured_output_llm
from internal.core.telemetry import traced_llm_stream

logger = logging.getLogger(__name__)

# 直答（退化）路径的断点位置哨兵：普通子任务断点用 spec.order（>=1），
# 直答路径无子任务、无 order，用固定负值定位断点，has_resumable_checkpoints 命中后可「继续执行」。
_DIRECT_ANSWER_CHECKPOINT_ORDER = -1

# 单个前置子任务产出注入到后置提问里的字符上限：超过则截断并标注。
# 取 8000 ≈ 一次代码级回答的量，3 个前置也不会顶爆常见 32k 上下文。
_UPSTREAM_CONTEXT_LIMIT = 8000


class OrchestratorAgent(BaseAgent):
    """编排器智能体"""

    def _build_agent(self) -> CompiledStateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("confirm_plan", self._confirm_plan_node)
        graph.add_node("direct_answer", self._direct_answer_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("summarize", self._summarize_node)
        graph.add_node("confirm_result", self._confirm_result_node)

        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", self._plan_condition)
        graph.add_conditional_edges("confirm_plan", self._replan_condition)
        graph.add_conditional_edges("execute", self._execute_condition)
        graph.add_edge("summarize", "confirm_result")
        graph.add_conditional_edges("confirm_result", self._confirm_done_condition)
        graph.add_edge("direct_answer", END)
        return graph.compile(checkpointer=self._checkpointer)

    @classmethod
    def _plan_condition(cls, state: AgentState) -> Literal["confirm_plan", "direct_answer", "execute"]:
        """plan 后：有子任务先经 confirm_plan 确认，无子任务直接回答。

        auto_replan（子任务失败自动重拆）时跳过确认框直接执行新计划——弹框会
        wait_for_plan_choice 阻塞最长 300s 等用户点，那就不叫自动重规划了。
        """
        if not state["sub_tasks"]:
            return "direct_answer"
        return "execute" if state.get("auto_replan") else "confirm_plan"

    @classmethod
    def _replan_condition(cls, state: AgentState) -> Literal["plan", "execute"]:
        """确认点 1：重新规划（plan_feedback 非空且重拆未超轮）回 plan，否则 execute。

        plan_attempts 递增配合 2 轮上限防止无限重拆。
        """
        if state.get("plan_feedback") and (state.get("plan_attempts") or 0) < 2:
            return "plan"
        return "execute"

    @classmethod
    def _execute_condition(cls, state: AgentState) -> Literal["plan", "summarize"]:
        """execute 后：子任务失败且重拆预算未用尽则自动回 plan，否则进 summarize。

        判定与预算都在 _execute_node 里做（它写 auto_replan），这里只按标记路由，
        避免条件函数改不了 state 造成"判了但没记下原因"。
        """
        return "plan" if state.get("auto_replan") else "summarize"

    @classmethod
    def _confirm_done_condition(cls, state: AgentState) -> Literal["plan", "__end__"]:
        """确认点 2：重新生成（regenerate 标记）回 plan，否则结束"""
        return "plan" if state.get("regenerate") else END

    @staticmethod
    def _coerce_int_list(value) -> list[int]:
        """把 LLM 给出的依赖字段归一化为 int 列表：兼容字符串化 JSON、单值、混入非数字。"""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return []
        if isinstance(value, int):
            return [value]
        if not isinstance(value, list):
            return []
        out: list[int] = []
        for item in value:
            try:
                num = int(item)
            except (TypeError, ValueError):
                continue
            if num not in out:
                out.append(num)
        return out

    @staticmethod
    def _build_waves(specs: list[SubTaskSpec]) -> list[list[SubTaskSpec]]:
        """按 depends_on 拓扑分批（Kahn）。同批内可并行；成环时断环而不是永久挂死。

        LLM 输出的依赖不可信（可能自依赖、指向不存在的 order、或 A→B→A 成环），
        而调度器一旦等不到前置结果就会卡住整个回答，所以这里保证一定能有进展：
        无就绪节点时，把剩余里 order 最小的一个当作就绪并丢弃其未满足依赖（结果可预期）。
        """
        by_order = {s.order: s for s in specs}
        deps = {
            s.order: {d for d in (s.depends_on or []) if d in by_order and d != s.order}
            for s in specs
        }
        waves: list[list[SubTaskSpec]] = []
        resolved: set[int] = set()
        remaining = [s.order for s in specs]
        while remaining:
            ready = [o for o in remaining if deps[o] <= resolved]
            if not ready:
                forced = min(remaining)
                logger.warning(
                    "编排器子任务依赖成环/悬空，断开 order=%s 的未满足依赖 %s",
                    forced, sorted(deps[forced] - resolved),
                )
                deps[forced] = set()
                ready = [forced]
            waves.append([by_order[o] for o in ready])
            resolved.update(ready)
            remaining = [o for o in remaining if o not in ready]
        return waves

    def _plan_node(self, state: AgentState) -> AgentState:
        """规划节点：LLM 结构化输出子任务清单"""
        cfg = self.agent_config.orchestrator_config or {}
        max_sub_tasks = cfg.get("max_sub_tasks", 5)
        # 规划提示词列出可用工具名，供 required_tools 按名选取
        available_tools = ", ".join(t.name for t in self.agent_config.tools) or "无"
        system_prompt = ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE.format(
            max_sub_tasks=max_sub_tasks, available_tools=available_tools,
        )
        # 提示词里列了可用工具会导致 DeepSeek 误调用工具，且 DeepSeek v4 不支持强制
        # tool_choice；plan 节点用 json_mode（提示词含 "json"）避免 function_calling 约束不住。
        plan_llm = build_structured_output_llm(self.llm, SubTaskPlanInput, method="json_mode")
        # 重新规划反馈（确认点1 replan / 确认点2 重新生成）：用户补充要求拼进 prompt
        feedback = state.get("plan_feedback", "")
        if feedback:
            human_content = f"{state['query']}\n\n用户补充要求：{feedback}"
        else:
            human_content = state["query"]
        # 健壮性：LLM 函数调用输出不稳定（偶发缺失必填字段/字符串化数组/把 task_id 填成字符串），
        # 解析失败重试一次；仍失败则退化为带全部工具的直接回答（_direct_answer_node 绑定工具），
        # 避免整个编排挂起或工具丢失。但"输出/上下文超长"这类不可恢复错误不降级——
        # 静默降级会让前端收不到任何事件、任务莫名停止（生产实测）；此处直接抛出，
        # 由基类 listen 捕获并以 ERROR 事件透传给前端。
        plan = None
        last_error: Exception | None = None
        length_error = False
        for attempt in (1, 2):
            try:
                plan = plan_llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ])
                break
            except Exception as e:
                last_error = e
                length_error = length_error or is_length_overflow_error(e)
                logger.exception("任务分解规划第 %s 次解析失败", attempt)
        if plan is None and length_error and last_error is not None:
            raise last_error
        # LLM 结构化输出可能返回 pydantic 模型或 dict（raw 模式），统一取 subtasks
        raw_specs = []
        if plan is not None:
            raw_specs = plan.get("subtasks") if isinstance(plan, dict) else (plan.subtasks or [])
        # 归一化：丢弃关键字段缺失项；required_tools 字符串化时转回列表；order 缺失在归一化后按位置补全；
        # task_id 由系统派发 uuid4()（LLM schema 已不含该字段，杜绝 open_page_1 这类字符串触发校验失败）
        normalized: list[SubTaskSpec] = []
        for spec in raw_specs[:max_sub_tasks]:
            title = getattr(spec, "title", "") or ""
            role_prompt = getattr(spec, "role_prompt", "") or ""
            if not title or not role_prompt:
                continue
            required_tools = getattr(spec, "required_tools", [])
            if isinstance(required_tools, str):
                try:
                    parsed = json.loads(required_tools)
                    required_tools = parsed if isinstance(parsed, list) else []
                except Exception:
                    required_tools = []
            if isinstance(spec, SubTaskSpec):
                # 兼容注入的 SubTaskSpec（测试/断点语义依赖同一对象被原地补齐 task_id）
                spec.required_tools = required_tools
                spec.depends_on = self._coerce_int_list(getattr(spec, "depends_on", []))
                spec.task_id = spec.task_id or uuid.uuid4()
                normalized.append(spec)
            else:
                # 生产路径：LLM 输出 SubTaskPlanInputSpec（无 task_id），转换并派发 task_id
                normalized.append(SubTaskSpec(
                    order=getattr(spec, "order", None),
                    title=title,
                    role_prompt=role_prompt,
                    expect_output=getattr(spec, "expect_output", "") or "",
                    required_tools=required_tools,
                    depends_on=self._coerce_int_list(getattr(spec, "depends_on", [])),
                    task_id=uuid.uuid4(),
                ))
        for i, spec in enumerate(normalized):
            if spec.order is None:
                spec.order = i + 1
        # order 是依赖声明与结果归并的键：LLM 重号会让 results[order] 互相覆盖、
        # 依赖指向歧义，所以按位置重号保证唯一
        if len({s.order for s in normalized}) != len(normalized):
            logger.warning("编排器子任务 order 重复，按位置重号为 1..%d", len(normalized))
            for i, spec in enumerate(normalized):
                spec.order = i + 1
        # 丢弃指向不存在 order 的依赖：SUB_TASK_PLAN 事件与确认框展示的就是将要执行的依赖，
        # 不能出现"界面画了一条永远等不到的边"
        valid_orders = {s.order for s in normalized}
        for spec in normalized:
            spec.depends_on = [d for d in spec.depends_on if d in valid_orders]
        specs = normalized

        # 注：仅在有子任务时发布 SUB_TASK_PLAN（退化为 direct_answer 时不发计划事件）
        if specs:
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(), task_id=state["task_id"],
                event=QueueEvent.SUB_TASK_PLAN,
                thought=json.dumps([s.model_dump(exclude={"task_id"}) for s in specs], ensure_ascii=False),
                message=messages_to_dict(state["messages"]),
            ))
        # 计划代际：每次产出新计划生成新 plan_id（replan/regenerate 重拆即新代际，
        # execute 前按代际失效旧断点，防"重拆后错误复用旧 complete 缓存"）
        return {"sub_tasks": specs, "plan_id": uuid.uuid4()}

    def _confirm_plan_node(self, state: AgentState) -> AgentState:
        """任务分配确认：发布 ask_user 展示子任务方案，等待用户确认/重新规划"""
        specs = state["sub_tasks"]
        if not specs:
            return {"sub_tasks": specs}  # 无子任务（direct_answer 场景）不弹框

        question = "请确认任务分配方案：勾选需要执行的子任务"
        options = [s.title for s in specs]
        sub_task_options = [s.model_dump(exclude={"task_id"}) for s in specs]
        tool_input = {
            "question": "请确认任务分配方案",
            "options": options,
            "sub_task_options": sub_task_options,
        }
        ask_event_id = uuid.uuid4()
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=ask_event_id, task_id=state["task_id"],
            event=QueueEvent.ASK_USER,
            question=question,
            options=options,
            sub_task_options=sub_task_options,
            allow_custom=True,
            tool=ASK_USER_TOOL_NAME,
            tool_input=tool_input,
            message=messages_to_dict(state["messages"]),
            latency=0,
        ))

        action, keep_orders, custom, skipped = AgentQueueManager.wait_for_plan_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
        if skipped:
            return {"sub_tasks": specs, "plan_feedback": ""}
        if action == "replan" or custom:
            return {
                "plan_feedback": custom,
                "sub_tasks": [],
                "plan_attempts": (state.get("plan_attempts") or 0) + 1,
            }
        # 确认：按 keep_orders 过滤（空 keep_orders 但确认 → 全选），并清除 plan_feedback 防止回环
        keep = set(keep_orders) if keep_orders else {s.order for s in specs}
        filtered = [s for s in specs if s.order in keep]
        # 同 event_id republish 带 choice（落库回显用）：choice 序列化用户最终选择，
        # 历史刷新后 plan 模式据此回显"已确认执行：[保留项]"并恢复只读
        self._republish_ask_user_choice(
            state, ask_event_id, question=question, options=options,
            tool_input=tool_input, sub_task_options=sub_task_options,
            choice=json.dumps({"action": "confirm", "keep_orders": keep_orders}, ensure_ascii=False),
        )
        return {"sub_tasks": filtered, "plan_feedback": ""}

    def _confirm_result_node(self, state: AgentState) -> AgentState:
        """汇总确认：LLM 判断汇总答案是否有歧义，有则弹框"""
        verdict = build_structured_output_llm(self.llm, ConfirmVerdict).invoke([
            SystemMessage(content=ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE),
            HumanMessage(content=state["query"]),
            SystemMessage(content=state.get("final_answer", "")),
        ])
        if not verdict.need_confirm:
            return {}  # 无歧义，直接 END

        question = f"汇总结果存在以下需要确认的点：{verdict.reason}\n请选择："
        options = ["确认完成", "重新生成"]
        tool_input = {"question": verdict.reason, "options": options}
        ask_event_id = uuid.uuid4()
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=ask_event_id, task_id=state["task_id"],
            event=QueueEvent.ASK_USER,
            question=question,
            options=options,
            allow_custom=True,
            tool=ASK_USER_TOOL_NAME,
            tool_input=tool_input,
            message=messages_to_dict(state.get("messages", [])),
            latency=0,
        ))
        choice, skipped, custom = AgentQueueManager.wait_for_choice(
            state["task_id"], timeout=ASK_USER_WAIT_TIMEOUT, event_id=str(ask_event_id),
        )
        if skipped or choice == "确认完成":
            if not skipped:
                self._republish_ask_user_choice(
                    state, ask_event_id, question=question, options=options,
                    tool_input=tool_input, choice="确认完成",
                )
            return {}  # 完成（超时也按完成）
        # 重新生成
        self._republish_ask_user_choice(
            state, ask_event_id, question=question, options=options,
            tool_input=tool_input,
            choice=f"重新生成：{custom}" if custom else "重新生成",
        )
        return {
            "plan_feedback": custom or "", "sub_tasks": [],
            "plan_attempts": (state.get("plan_attempts") or 0) + 1, "regenerate": True,
        }

    def _republish_ask_user_choice(self, state: AgentState, ask_event_id, *, question: str, options: list, tool_input: dict, choice: str, sub_task_options: list | None = None) -> None:
        """同 event_id republish 带 choice 的 ASK_USER 事件（落库/历史回显用）"""
        kwargs: dict = {
            "id": ask_event_id,
            "task_id": state["task_id"],
            "event": QueueEvent.ASK_USER,
            "question": question,
            "options": options,
            "allow_custom": True,
            "choice": choice,
            "tool": ASK_USER_TOOL_NAME,
            "tool_input": tool_input,
            "message": messages_to_dict(state.get("messages", [])),
            "latency": 0,
        }
        if sub_task_options is not None:
            kwargs["sub_task_options"] = sub_task_options
        self.agent_queue_manager.publish(state["task_id"], AgentThought(**kwargs))

    def _direct_answer_node(self, state: AgentState) -> AgentState:
        """退化直答：无子任务时由子 Agent 直接回答。

        与 _run_subtask_inner 同源支持断点续跑：按 message_id（续跑时 resume_message_id）
        在固定哨兵位置 _DIRECT_ANSWER_CHECKPOINT_ORDER 保存/恢复断点。
        直答常是"长文件构建/长推理"任务（多次 fs_write），父级 listen 600s 超时或用户
        停止时，若已周期落盘断点，前端 can_resume 命中显示「继续执行」。
        """
        from package.database import build_engine, worker_run
        from internal.container import create_sub_task_service

        cfg = self.agent_config.orchestrator_config or {}
        resume_mode = cfg.get("resume_mode", "auto")
        message_id = state.get("message_id") or state.get("conversation_id")
        app_id = state.get("app_id") or self.agent_config.user_id
        # 断点按 message_id 定位：续跑（resume_message_id）指回原消息，普通运行用本次 message_id
        checkpoint_message_id = state.get("resume_message_id") or message_id
        position = _DIRECT_ANSWER_CHECKPOINT_ORDER
        direct_spec = SubTaskSpec(
            order=position, title="直接回答",
            role_prompt=self.agent_config.preset_prompt or "",
        )

        sub_agent = self._build_direct_answer_agent()
        should_resume = False
        checkpoint = None
        allow_resume = resume_mode == "auto" or state.get("resume_trigger")
        if allow_resume and checkpoint_message_id is not None:
            def _query_checkpoint(session):
                svc = create_sub_task_service(session)
                return svc.get_checkpoint(checkpoint_message_id, position)
            checkpoint = worker_run(_query_checkpoint, commit_on_success=False, engine_factory=build_engine)
            if checkpoint is not None and (not state["query"] or checkpoint.query == state["query"]):
                should_resume = checkpoint.status in ("running", "stop", "timeout", "error")

        sub_task_id = uuid.uuid4()
        if should_resume:
            messages = [self._message_dict_to_langchain(m) for m in (checkpoint.messages or [])]
            input_data = {
                "messages": messages,
                "history": [],
                "iteration_count": checkpoint.iteration_count,
                "resume": True,
                "task_id": sub_task_id,
                "long_term_memory": state.get("long_term_memory", ""),
                "user_profile": state.get("user_profile", ""),
                "episodic_memory": state.get("episodic_memory", ""),
                "procedural_instructions": state.get("procedural_instructions", ""),
            }
            answer_parts = [checkpoint.partial_answer or ""]
            # 断点恢复标记：以「思考」事件透出（不入 sub_task_id 分组，避免直答被误分组为子任务）
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_THOUGHT,
                thought="（已从断点恢复，继续执行）",
                message=messages_to_dict(state["messages"]),
            ))
        else:
            input_data = {
                "messages": [self.llm.convert_to_human_message(state["query"], None)],
                "history": [],
                "iteration_count": 0,
                "resume": False,
                "task_id": sub_task_id,
                "long_term_memory": state.get("long_term_memory", ""),
                "user_profile": state.get("user_profile", ""),
                "episodic_memory": state.get("episodic_memory", ""),
                "procedural_instructions": state.get("procedural_instructions", ""),
            }
            answer_parts = []

        sub_error = None
        timed_out = False
        stopped = False
        last_state_messages = None
        total_token_count = 0
        total_price = 0.0
        event_count = 0
        last_save_at = time.time()
        for thought in sub_agent.stream(input_data):
            if thought.event in (QueueEvent.PING, QueueEvent.AGENT_END):
                continue
            if thought.event == QueueEvent.STOP:
                stopped = True
                break
            if thought.event == QueueEvent.TIMEOUT:
                timed_out = True
                break
            if thought.event == QueueEvent.ERROR:
                sub_error = thought.observation or "直接回答执行失败"
                break
            # 直答退化路径：本 Agent 即"子 Agent"，它的 task_id 是 input_data["task_id"]（uuid4）。
            # 本地工具运行时的 _handle_local_tool 在"子 Agent 的 task_id"上等待工具结果，
            # 且插件回传的 task_id 取自 SSE 帧里的 thought.task_id——两者必须一致，才能唤醒。
            # 因此桥接进父队列（为了让 SSE 读到事件）时**不能改写 thought.task_id**，
            # 只能把它也桥接进来（保留子 task_id，等价子任务路径 _run_subtask_inner 的做法）。
            bridged = thought
            self.agent_queue_manager.forward(state["task_id"], bridged)
            last_state_messages = bridged.message
            total_token_count += thought.total_token_count or 0
            total_price += thought.total_price or 0
            if thought.event == QueueEvent.AGENT_MESSAGE:
                answer_parts.append(thought.answer)
            event_count += 1
            # 周期落盘 running 断点：长直答（多次文件构建）超时/停止后能断点续跑
            if event_count % 10 == 0 and (time.time() - last_save_at) >= 10 and state.get("conversation_id"):
                def _save_periodic(session):
                    svc = create_sub_task_service(session)
                    return svc.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=checkpoint_message_id, position=position,
                        plan_id=state.get("plan_id"), query=state["query"],
                        spec=direct_spec, status="running",
                        messages=last_state_messages or messages_to_dict(input_data["messages"]),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer="".join(answer_parts),
                        total_token_count=total_token_count, total_price=total_price,
                    )
                worker_run(_save_periodic, engine_factory=build_engine)
                last_save_at = time.time()

        answer = "".join(answer_parts)

        # 终态断点落库：完成写 complete（不可续跑）；超时/停止/出错写对应状态（可续跑）
        if state.get("conversation_id"):
            terminal = "complete"
            if sub_error:
                terminal = "error"
            elif timed_out:
                terminal = "timeout"
            elif stopped:
                terminal = "stop"
            try:
                def _save_terminal(session):
                    svc = create_sub_task_service(session)
                    return svc.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=checkpoint_message_id, position=position,
                        plan_id=state.get("plan_id"), query=state["query"],
                        spec=direct_spec, status=terminal,
                        messages=last_state_messages or messages_to_dict(input_data["messages"]),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer=answer,
                        total_token_count=total_token_count, total_price=total_price,
                    )
                worker_run(_save_terminal, engine_factory=build_engine)
            except Exception:
                logger.exception("保存直答断点失败 message=%s", checkpoint_message_id)

        if sub_error:
            # 模型错误不能伪装成"正常结束"：否则前端只看到空回答 + AGENT_END，读不到
            # "余额不足"这类可读提示，chat_runner 也会把这次 run 记成 succeeded。
            self.agent_queue_manager.publish_error(state["task_id"], sub_error)
        else:
            self.agent_queue_manager.publish(state["task_id"], AgentThought(
                id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
            ))
        return {"messages": [AIMessage(content=answer)]}

    def _build_direct_answer_agent(self):
        """退化直接回答子 Agent：按模型能力选 FunctionCallAgent / ReACTAgent，绑定全部工具"""
        cls = FunctionCallAgent if ModelFeature.TOOL_CALL in self.llm.features else ReACTAgent
        return cls(
            name="direct-answer",
            llm=self.llm,
            agent_config=AgentConfig(
                user_id=self.agent_config.user_id,
                invoke_from=self.agent_config.invoke_from,
                max_iteration_count=self.agent_config.max_iteration_count,
                preset_prompt=self.agent_config.preset_prompt,
                enable_long_term_memory=self.agent_config.enable_long_term_memory,
                tools=list(self.agent_config.tools),
                review_config=self.agent_config.review_config,
                local_tool_runtime=self.agent_config.local_tool_runtime,
            ),
        )

    def _execute_node(self, state: AgentState) -> AgentState:
        """并行执行子任务：断点恢复 / 缓存复用 / 全新执行，事件桥接进主队列"""
        # 子任务线程由 worker_run 承载（独立 loop + AsyncSession），不需要 Flask app context。
        specs = state["sub_tasks"]
        cfg = self.agent_config.orchestrator_config or {}
        max_parallel = cfg.get("max_parallel", 3)
        resume_mode = cfg.get("resume_mode", "auto")
        sub_task_timeout = cfg.get("sub_task_timeout", 300)
        results: dict[int, SubTaskResult] = {}
        running_ids: set = set()
        ids_lock = threading.Lock()
        execution_done = threading.Event()

        # 代际失效：replan（确认点1 重新规划）/ regenerate（确认点2 重新生成）后，本计划已是
        # 新代际（plan_id 已换新），旧代际断点必须清空——否则 execute 按 message_id+position
        # 复用上一代计划落下的 complete 缓存/断点，导致"重拆后拿到旧计划的结果"。
        # resume（stop/timeout/error 后重发同 query）时 plan_attempts=0 / 无 regenerate，不清断点，续跑语义保持。
        checkpoint_message_id = state.get("resume_message_id") or state.get("message_id")
        if (
            checkpoint_message_id is not None
            and ((state.get("plan_attempts") or 0) > 0 or state.get("regenerate"))
        ):
            from package.database import build_engine, worker_run
            from internal.container import create_sub_task_service

            def _clear_old_plan(session):
                svc = create_sub_task_service(session)
                return svc.clear_checkpoints(message_id=checkpoint_message_id)

            try:
                # 子任务线程由 worker_run 承载（独立 loop + AsyncSession）；必须传 engine_factory——
                # 全局默认 engine 的 asyncpg 连接绑定首次创建时的 loop，跨 loop 复用会抛
                # "Event loop is closed" / "another operation is in progress"（与 _run_subtask_inner 同源）。
                worker_run(_clear_old_plan, engine_factory=build_engine)
                logger.info(
                    "编排器代际失效：重拆后清空旧断点 message=%s plan_attempts=%s regenerate=%s",
                    checkpoint_message_id, state.get("plan_attempts"), state.get("regenerate"),
                )
            except Exception:
                logger.exception("编排器代际失效清断点失败 message=%s", checkpoint_message_id)

        # 停止监控：主任务被停止时，给所有运行中子任务设置停止标志；执行结束无子任务可监控时立即退出。
        # 注意：停止后不立即 return——max_parallel 限制下部分子任务可能尚未注册（worker 稍后启动），
        # 需持续轮询直至 execution_done，确保迟注册的子任务也能收到停止标志（E2E 实测发现的竞态）。
        def monitor_stop():
            while True:
                with ids_lock:
                    if execution_done.is_set() and not running_ids:
                        return
                    stopped = self.agent_queue_manager._is_stopped(state["task_id"])
                    ids = list(running_ids)
                if stopped and ids:
                    for tid in ids:
                        try:
                            AgentQueueManager.set_stop_flag(
                                tid, self.agent_config.invoke_from, self.agent_config.user_id,
                            )
                        except Exception:
                            logger.exception("设置子任务停止标志失败 tid=%s", tid)
                time.sleep(0.5)

        monitor = threading.Thread(target=monitor_stop, daemon=True)
        monitor.start()

        execute_started = time.perf_counter()
        try:
            # 按 depends_on 分批（同批并行、批间串行）。原先是一次性把全部子任务丢进线程池，
            # 等于强制"全并行 + 互不知情"，声明了依赖也拿不到上游产出。
            for wave in self._build_waves(specs):
                # 前置没成功的后置子任务拿不到输入，直接判失败，而不是拿脏上下文硬跑一遍
                for spec in wave:
                    unmet = [
                        d for d in (spec.depends_on or [])
                        if results.get(d) is None or results[d].status != "normal"
                    ]
                    if unmet:
                        upstream = "、".join(f"#{d}" for d in unmet)
                        logger.warning("子任务 order=%s 的前置 %s 未成功，标记为失败", spec.order, upstream)
                        results[spec.order] = SubTaskResult(
                            order=spec.order, title=spec.title, status="error",
                            error=f"前置子任务 {upstream} 未成功完成",
                        )
                runnable = [s for s in wave if s.order not in results]
                if not runnable:
                    continue
                # 预算护栏钩子：基类不限，GuardedOrchestratorAgent 按 token/花费/墙钟熔断
                allowed, why = self._budget_allows(state, results, time.perf_counter() - execute_started)
                if not allowed:
                    logger.warning("编排器预算熔断，剩余 %d 个子任务不再派发：%s", len(runnable), why)
                    for spec in runnable:
                        results[spec.order] = SubTaskResult(
                            order=spec.order, title=spec.title, status="error", error=why,
                        )
                    return self._finish_results(state, results, budget_exhausted=True)
                with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                    futures = {
                        pool.submit(
                            self._run_subtask, state, spec, running_ids, ids_lock,
                            resume_mode, sub_task_timeout,
                            self._upstream_answers(spec, results),
                        ): spec
                        for spec in runnable
                    }
                    for fut in as_completed(futures):
                        spec = futures[fut]
                        try:
                            results[spec.order] = fut.result()
                        except Exception as e:
                            logger.exception("子任务执行失败 order=%s", spec.order)
                            results[spec.order] = SubTaskResult(
                                order=spec.order, title=spec.title, status="error", error=str(e),
                            )
        finally:
            # 通知监控线程执行已结束
            execution_done.set()
            monitor.join(timeout=5)

        return self._finish_results(state, results)

    def _budget_allows(
            self,
            state: AgentState,
            results: dict[int, SubTaskResult],
            elapsed: float = 0.0,
    ) -> tuple[bool, str]:
        """派发下一批前的预算闸门。基类不限流，由带护栏的编排引擎覆写。

        闸门放在批次边界而不是子任务中途：中途掐断会让子任务留下半截产出，
        批间断开则每个已启动的子任务都是完整结果，汇总与断点续跑语义不变。
        """
        return True, ""

    def _finish_results(
            self,
            state: AgentState,
            results: dict[int, SubTaskResult],
            *,
            budget_exhausted: bool = False,
    ) -> dict:
        """执行收尾：决定是否失败自动重规划（预算熔断造成的失败不重规划）。"""
        cfg = self.agent_config.orchestrator_config or {}
        results_list = [results[o] for o in sorted(results)]

        # 失败自动重规划：error/timeout 触发。用户主动 stop 不算失败——那是明确意图，
        # 自动重拆会把用户刚刚叫停的东西再跑一遍；预算熔断同理，重拆只会继续烧预算。
        failed = [r for r in results_list if r.status in ("error", "timeout")]
        attempts = state.get("plan_attempts") or 0
        if (
            failed
            and not budget_exhausted
            and cfg.get("auto_replan_on_failure", True)
            and attempts < 2
        ):
            reason = "；".join(f"#{r.order} {r.title}：{(r.error or r.status).strip()}" for r in failed)
            logger.warning("编排器子任务失败，自动重规划（第 %d 轮）：%s", attempts + 1, reason)
            return {
                "sub_results": results_list,
                "auto_replan": True,
                "replan_reason": reason,
                "plan_feedback": (
                    f"上一版计划执行到一半失败：{reason}。"
                    "请据此重新拆分——修正失败那一步的做法或换一条路径，不要原样重复已失败的子任务。"
                ),
                "plan_attempts": attempts + 1,
                "budget_exhausted": False,
            }
        return {
            "sub_results": results_list,
            "auto_replan": False,
            "replan_reason": "",
            "budget_exhausted": budget_exhausted,
        }

    @staticmethod
    def _upstream_answers(spec: SubTaskSpec, results: dict[int, SubTaskResult]) -> dict[int, str]:
        """取该子任务已成功的直接前置产出（order → answer）。"""
        return {
            d: results[d].answer
            for d in (spec.depends_on or [])
            if results.get(d) is not None and results[d].status == "normal" and results[d].answer
        }

    @staticmethod
    def _subtask_query(query: str, upstream: dict[int, str]) -> str:
        """把前置产出拼进提问：声明了依赖却拿不到上游结果，后置子任务只能重复做一遍前置的工作。

        截断而非报错：多个长回答很容易顶到模型上下文上限，宁可带省略标记也不要整轮失败。
        """
        if not upstream:
            return query
        blocks = "\n\n".join(
            f"【前置子任务 #{order} 的产出】\n"
            f"{answer if len(answer) <= _UPSTREAM_CONTEXT_LIMIT else answer[:_UPSTREAM_CONTEXT_LIMIT] + '…（已截断）'}"
            for order, answer in sorted(upstream.items())
        )
        return f"{query}\n\n{blocks}"

    def _run_subtask(
            self,
            state: AgentState,
            spec: SubTaskSpec,
            running_ids: set,
            ids_lock: threading.Lock,
            resume_mode: str,
            sub_task_timeout: int,
            upstream: dict[int, str] | None = None,
    ) -> SubTaskResult:
        """单个子任务入口：工作线程内直接执行（不再需要 Flask app context）"""
        return self._run_subtask_inner(
            state, spec, running_ids, ids_lock, resume_mode, sub_task_timeout, upstream,
        )

    def _run_subtask_inner(
            self,
            state: AgentState,
            spec: SubTaskSpec,
            running_ids: set,
            ids_lock: threading.Lock,
            resume_mode: str,
            sub_task_timeout: int,
            upstream: dict[int, str] | None = None,
    ) -> SubTaskResult:
        """单个子任务：断点查询 → 恢复续跑 / 复用缓存 / 全新执行；桥接事件；周期落盘"""
        # SubTaskService 通过 container 工厂构造（worker_run 内 loop+session）
        # 子任务在 ThreadPoolExecutor 工作线程里 asyncio.run 新 loop，
        # 若 worker_run 用全局默认 engine（uvicorn lifespan 建的连接池），asyncpg 连接跨 loop
        # 复用抛 "cannot perform operation: another operation is in progress"（与 celery threads 池同源）。
        # 必须每子任务独立 engine（engine_factory：创建与 dispose 同 loop）。
        from package.database import build_engine, worker_run
        from internal.container import create_sub_task_service

        worker_engine_factory = build_engine

        # 断点查询通过 worker_run 桥接（需要 AsyncSession）
        sub_task_id = spec.task_id or uuid.uuid4()
        app_id = state.get("app_id") or self.agent_config.user_id
        message_id = state.get("message_id") or state.get("conversation_id")
        with ids_lock:
            running_ids.add(sub_task_id)
        started = time.perf_counter()
        should_resume = False
        reuse_answer = None
        checkpoint = None
        input_data: dict = {}
        answer_parts: list = []

        # 断点归属的消息 id：续跑（resume_message_id）指回原消息，普通运行用本次 run 的 message_id。
        # 断点按 message_id 定位（不再用 conversation_id+position 共享键，避免同会话多轮互相覆盖）。
        checkpoint_message_id = state.get("resume_message_id") or message_id

        # 1、断点查询（auto 模式或显式恢复触发）
        allow_resume = resume_mode == "auto" or state.get("resume_trigger")
        if allow_resume and checkpoint_message_id is not None:
            # 查询断点需要 AsyncSession，通过 worker_run 桥接
            def _query_checkpoint(session):
                svc = create_sub_task_service(session)
                return svc.get_checkpoint(checkpoint_message_id, spec.order)
            checkpoint = worker_run(_query_checkpoint, commit_on_success=False, engine_factory=worker_engine_factory)
            if checkpoint is not None and (not state["query"] or checkpoint.query == state["query"]):
                if checkpoint.status == "complete":
                    reuse_answer = checkpoint.partial_answer
                elif checkpoint.status in ("running", "stop", "timeout", "error"):
                    should_resume = True

        # 2、已完成缓存直接复用
        if reuse_answer is not None:
            with ids_lock:
                running_ids.discard(sub_task_id)
            return SubTaskResult(
                order=spec.order, title=spec.title, status="normal",
                answer=reuse_answer, latency=0.0, resumed=False,
            )

        # 恢复提示：SUB_TASK_START 标注"已从断点恢复"
        start_thought = spec.role_prompt[:200]
        if should_resume:
            start_thought = f"（已从断点恢复，继续执行）{start_thought}"

        try:
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_START, spec, thought=start_thought, sub_task_id=sub_task_id)

            sub_agent = self._build_sub_agent(spec, sub_task_id, state.get("plan_id"))
            if should_resume:
                messages = [self._message_dict_to_langchain(m) for m in (checkpoint.messages or [])]
                input_data = {
                    "messages": messages,
                    "history": [],
                    "iteration_count": checkpoint.iteration_count,
                    "resume": True,
                    "task_id": sub_task_id,
                }
                answer_parts = [checkpoint.partial_answer or ""]
            else:
                input_data = {
                    "messages": [self.llm.convert_to_human_message(
                        self._subtask_query(state["query"], upstream or {}), None,
                    )],
                    "history": [],
                    "iteration_count": 0,
                    "resume": False,
                    "task_id": sub_task_id,
                }
                answer_parts = []

            event_count = 0
            last_save_at = time.time()
            timed_out = False
            sub_error = None
            total_token_count = 0
            total_price = 0.0
            last_state_messages = None
            for thought in sub_agent.stream(input_data):
                if sub_task_timeout and (time.perf_counter() - started) > sub_task_timeout:
                    timed_out = True
                    break
                # 子任务被停止：立即跳出，走下方 _is_stopped 分支落 stop 断点并快速收尾。
                # （原实现 continue 会让子 Agent 图继续跑完整个 LLM 循环，停止形同虚设。）
                if thought.event == QueueEvent.STOP:
                    break
                if thought.event in (QueueEvent.PING, QueueEvent.AGENT_END, QueueEvent.TIMEOUT):
                    continue
                if thought.event == QueueEvent.ERROR:
                    sub_error = thought.observation or "子任务执行失败"
                    continue
                bridged = thought.model_copy(update={"sub_task_id": sub_task_id, "sub_task_title": spec.title})
                self.agent_queue_manager.forward(state["task_id"], bridged)
                last_state_messages = bridged.message
                total_token_count += thought.total_token_count or 0
                total_price += thought.total_price or 0
                if thought.event == QueueEvent.AGENT_MESSAGE:
                    answer_parts.append(thought.answer)
                event_count += 1
                # 周期落盘
                if event_count % 10 == 0 and (time.time() - last_save_at) >= 10 and state.get("conversation_id"):
                    def _save_periodic(session):
                        svc = create_sub_task_service(session)
                        return svc.save_checkpoint(
                            app_id=app_id, conversation_id=state["conversation_id"],
                            message_id=checkpoint_message_id, position=spec.order,
                            plan_id=state.get("plan_id"),
                            query=state["query"], spec=spec, status="running",
                            messages=last_state_messages or messages_to_dict(input_data["messages"]),
                            iteration_count=input_data.get("iteration_count", 0),
                            partial_answer="".join(answer_parts),
                        )
                    worker_run(_save_periodic, engine_factory=worker_engine_factory)
                    last_save_at = time.time()
        except Exception as e:
            logger.exception("子任务异常 order=%s", spec.order)
            if state.get("conversation_id"):
                try:
                    def _save_error(session):
                        svc = create_sub_task_service(session)
                        return svc.save_checkpoint(
                            app_id=app_id, conversation_id=state["conversation_id"],
                            message_id=checkpoint_message_id, position=spec.order,
                            plan_id=state.get("plan_id"),
                            query=state["query"], spec=spec, status="error",
                            messages=last_state_messages or messages_to_dict(input_data.get("messages", [])),
                            iteration_count=input_data.get("iteration_count", 0),
                            partial_answer="".join(answer_parts),
                        )
                    worker_run(_save_error, engine_factory=worker_engine_factory)
                except Exception:
                    logger.exception("保存错误断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"error: {e}", latency=time.perf_counter() - started, sub_task_id=sub_task_id, total_token_count=total_token_count, total_price=total_price)
            return SubTaskResult(order=spec.order, title=spec.title, status="error", error=str(e), latency=time.perf_counter() - started, total_token_count=total_token_count, total_price=total_price, resumed=should_resume)
        finally:
            with ids_lock:
                running_ids.discard(sub_task_id)

        answer = "".join(answer_parts)

        # 错误分支：子 Agent 图线程异常
        if sub_error:
            if state.get("conversation_id"):
                try:
                    def _save_sub_error(session):
                        svc = create_sub_task_service(session)
                        return svc.save_checkpoint(
                            app_id=app_id, conversation_id=state["conversation_id"],
                            message_id=checkpoint_message_id, position=spec.order,
                            plan_id=state.get("plan_id"),
                            query=state["query"], spec=spec, status="error",
                            messages=last_state_messages or messages_to_dict(input_data.get("messages", [])),
                            iteration_count=input_data.get("iteration_count", 0),
                            partial_answer=answer,
                        )
                    worker_run(_save_sub_error, engine_factory=worker_engine_factory)
                except Exception:
                    logger.exception("保存错误断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"error: {sub_error}", latency=time.perf_counter() - started, sub_task_id=sub_task_id, total_token_count=total_token_count, total_price=total_price)
            return SubTaskResult(order=spec.order, title=spec.title, status="error", error=sub_error, latency=time.perf_counter() - started, total_token_count=total_token_count, total_price=total_price, resumed=should_resume)

        # 超时分支
        if timed_out:
            try:
                AgentQueueManager.set_stop_flag(
                    sub_task_id, self.agent_config.invoke_from, self.agent_config.user_id,
                )
            except Exception:
                logger.exception("设置子任务停止标志失败 order=%s", spec.order)
            if state.get("conversation_id"):
                try:
                    def _save_timeout(session):
                        svc = create_sub_task_service(session)
                        return svc.save_checkpoint(
                            app_id=app_id, conversation_id=state["conversation_id"],
                            message_id=checkpoint_message_id, position=spec.order,
                            plan_id=state.get("plan_id"),
                            query=state["query"], spec=spec, status="timeout",
                            messages=last_state_messages or messages_to_dict(input_data["messages"]),
                            iteration_count=input_data.get("iteration_count", 0),
                            partial_answer=answer,
                        )
                    worker_run(_save_timeout, engine_factory=worker_engine_factory)
                except Exception:
                    logger.exception("保存超时断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"timeout: {answer[:300]}", latency=time.perf_counter() - started, sub_task_id=sub_task_id, total_token_count=total_token_count, total_price=total_price)
            return SubTaskResult(order=spec.order, title=spec.title, status="timeout", answer=answer, latency=time.perf_counter() - started, total_token_count=total_token_count, total_price=total_price, resumed=should_resume)

        # 停止分支
        if self.agent_queue_manager._is_stopped(sub_task_id):
            if state.get("conversation_id"):
                try:
                    def _save_stop(session):
                        svc = create_sub_task_service(session)
                        return svc.save_checkpoint(
                            app_id=app_id, conversation_id=state["conversation_id"],
                            message_id=checkpoint_message_id, position=spec.order,
                            plan_id=state.get("plan_id"),
                            query=state["query"], spec=spec, status="stop",
                            messages=last_state_messages or messages_to_dict(input_data["messages"]),
                            iteration_count=input_data.get("iteration_count", 0),
                            partial_answer=answer,
                        )
                    worker_run(_save_stop, engine_factory=worker_engine_factory)
                except Exception:
                    logger.exception("保存停止断点失败")
            self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=f"stop: {answer[:300]}", latency=time.perf_counter() - started, sub_task_id=sub_task_id, total_token_count=total_token_count, total_price=total_price)
            return SubTaskResult(order=spec.order, title=spec.title, status="stop", answer=answer, latency=time.perf_counter() - started, total_token_count=total_token_count, total_price=total_price, resumed=should_resume)

        # 3、完成：缓存最终答案
        if state.get("conversation_id"):
            try:
                def _save_complete(session):
                    svc = create_sub_task_service(session)
                    return svc.save_checkpoint(
                        app_id=app_id, conversation_id=state["conversation_id"],
                        message_id=checkpoint_message_id, position=spec.order,
                        plan_id=state.get("plan_id"),
                        query=state["query"], spec=spec, status="complete",
                        messages=last_state_messages or messages_to_dict(input_data["messages"]),
                        iteration_count=input_data.get("iteration_count", 0),
                        partial_answer=answer,
                    )
                worker_run(_save_complete, engine_factory=worker_engine_factory)
            except Exception:
                logger.exception("保存完成断点失败")
        self._publish_sub_task_event(state, QueueEvent.SUB_TASK_END, spec, observation=answer[:500], latency=time.perf_counter() - started, sub_task_id=sub_task_id, total_token_count=total_token_count, total_price=total_price)
        return SubTaskResult(order=spec.order, title=spec.title, status="normal", answer=answer, latency=time.perf_counter() - started, total_token_count=total_token_count, total_price=total_price, resumed=should_resume)

    @staticmethod
    def _message_dict_to_langchain(m: dict):
        """将 messages_to_dict 输出还原为 LangChain 消息"""
        from langchain_core.load import loads
        from langchain_core.messages import BaseMessage, messages_from_dict
        try:
            restored = loads(json.dumps(m))
            if isinstance(restored, BaseMessage):
                return restored
            return messages_from_dict([m])[0]
        except Exception:
            return HumanMessage(content=str(m))

    def _build_sub_agent(self, spec: SubTaskSpec, task_id: uuid.UUID | None = None, plan_id=None):
        """动态创建子 Agent（支持 tool_call 用 FunctionCallAgent，否则 ReACTAgent）"""
        cls = FunctionCallAgent if ModelFeature.TOOL_CALL in self.llm.features else ReACTAgent
        task_id = task_id or uuid.uuid4()
        run_context = (
            self._run_context.child(task_id, namespace=f"{self._run_context.namespace or 'root'}:{plan_id or 'legacy'}:{spec.order}")
            if self._run_context is not None else None
        )
        if spec.required_tools:
            tools = [t for t in self.agent_config.tools if t.name in spec.required_tools]
        else:
            tools = list(self.agent_config.tools)
        return cls(
            name=f"sub-{spec.order}",
            llm=self.llm,
            agent_config=AgentConfig(
                user_id=self.agent_config.user_id,
                invoke_from=self.agent_config.invoke_from,
                max_iteration_count=self.agent_config.max_iteration_count,
                preset_prompt=spec.role_prompt,
                tools=tools,
                review_config=self.agent_config.review_config,
                local_tool_runtime=self.agent_config.local_tool_runtime,
            ),
            checkpointer=self._checkpointer,
            run_context=run_context,
        )

    def _publish_sub_task_event(self, state: AgentState, event: QueueEvent, spec: SubTaskSpec, *, thought: str = "", observation: str = "", latency: float = 0.0, sub_task_id: uuid.UUID, total_token_count: int = 0, total_price: float = 0.0) -> None:
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=event,
            thought=thought, observation=observation, latency=latency,
            total_token_count=total_token_count, total_price=total_price,
            sub_task_id=sub_task_id, sub_task_title=spec.title,
            message=messages_to_dict(state["messages"]),
        ))

    def _summarize_node(self, state: AgentState) -> AgentState:
        """汇总节点：综合子任务结果生成最终答案"""
        lines = []
        for r in state["sub_results"]:
            body = r.answer if r.status == "normal" else f"（{r.status}）{r.error or '无结果'}"
            lines.append(f"【子任务{r.order}】{r.title}：\n{body}")
        prompt = ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE.format(
            query=state["query"], sub_results_text="\n".join(lines),
        )
        stream_id = uuid.uuid4()
        gathered = None
        for chunk in traced_llm_stream(self.llm, [SystemMessage(content=prompt)]):
            if gathered is None:
                gathered = chunk
            else:
                gathered += chunk
            if chunk.content:
                self.agent_queue_manager.publish(state["task_id"], AgentThought(
                    id=stream_id, task_id=state["task_id"],
                    event=QueueEvent.AGENT_MESSAGE,
                    thought=chunk.content, message=messages_to_dict(state["messages"]),
                    answer=chunk.content,
                ))
        # LLM 调用轨迹：完整输出（与流式 chunk 同 stream_id，消费端合并）
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=stream_id, task_id=state["task_id"],
            event=QueueEvent.AGENT_MESSAGE,
            message=messages_to_dict(state["messages"]),
            llm_output=getattr(gathered, "content", "") if gathered else "",
        ))
        self.agent_queue_manager.publish(state["task_id"], AgentThought(
            id=uuid.uuid4(), task_id=state["task_id"], event=QueueEvent.AGENT_END,
        ))
        final_answer = gathered.content if gathered else ""
        return {"messages": [gathered or AIMessage(content="")], "final_answer": final_answer}
