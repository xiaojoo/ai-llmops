#!/usr/bin/env python
"""
@Time    : 2026/2/8 20:45
@Author  : sunxiaojie
@File    : web_app_service.py
"""
import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.agent.agents import AgentQueueManager
from internal.core.request_context import get_request_context
from internal.entity.app_entity import AppStatus
from internal.entity.conversation_entity import InvokeFrom, MessageStatus, TERMINAL_RUN_STATUSES
from internal.exception import ForbiddenException, NotFoundException
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.model import Account, AgentRun, App, Conversation, Message
from internal.schema.web_app_schema import CodeActionReq, WebAppChatReq
from internal.service import BaseService

from .app_config_service import AppConfigService
from .attachment_service import AttachmentService
from .chat_runner import ChatRunner, _aiter_sync, agent_thought_to_sse_frame, merge_agent_thought
from .conversation_service import ConversationService
from .event_replay import run_event_log
from .language_model_service import LanguageModelService
from .memory_provider import MemoryProviderResolver
from .retrieval_service import RetrievalService

if TYPE_CHECKING:
    from internal.service.app_service import AppService

# 插件兜底：无可用已发布应用时，自动创建+发布的默认应用信息
DEFAULT_PLUGIN_APP_NAME = "WebApp 会话助手"
DEFAULT_PLUGIN_APP_DESC = "插件自动创建的默认应用"

logger = logging.getLogger(__name__)

# 会让 AgentQueueManager.publish 顺带 put(None) 收尾的那批事件：续传流看到它们就代表
# 这次 run 到此为止，可以落库了（与 publish 内的判定保持同一组）。
# 续传端点跟读事件日志的节奏与上限（上限与 AgentQueueManager.listen 的 600s 同量级）
_RESUME_POLL_INTERVAL_SECONDS = 0.2
_RESUME_POLL_TIMEOUT_SECONDS = 600
# 日志空转多久去查一次 run 状态：查太密是给数据库添活，查太疏会让已结束的 run 多挂一会儿
_RESUME_LIVENESS_CHECK_SECONDS = 1.0
# 帧里的终态事件名（QueueEvent 的 value）：续传端点只读日志，得自己从帧上认终态
_RESUME_TERMINAL_EVENT_NAMES = frozenset({"agent_end", "stop", "error", "timeout"})


def _parse_sse_frame(frame: str) -> tuple[int, str]:
    """从已序列化的 SSE 帧取回 (seq, event)。"""
    seq = 0
    event = ""
    for line in frame.split("\n"):
        if line.startswith("id:"):
            try:
                seq = int(line[3:].strip() or 0)
            except ValueError:
                seq = 0
        elif line.startswith("event:"):
            event = line[6:].strip()
    return seq, event



@dataclass
class WebAppService(BaseService):
    """WebApp服务"""
    db: AsyncSession
    retrieval_service: RetrievalService
    app_service: "AppService"
    app_config_service: AppConfigService
    conversation_service: ConversationService
    language_model_service: LanguageModelService
    chat_runner: ChatRunner
    memory_provider_resolver: MemoryProviderResolver
    attachment_service: AttachmentService

    async def bootstrap_web_app(self, account: Account) -> dict[str, Any]:
        """插件兜底：确保当前账号至少有一个已发布的 WebApp，返回可用 token 等信息。

        - 账号下已有已发布应用 → 复用（取最近创建的）；
        - 没有 → 自动创建 + 发布一个默认应用。
        供插件登录/每次刷新时调用，避免"没有已发布 App 就不可用"。
        """
        app = await self._first_published_app(account)
        if app is None:
            app = await self._create_and_publish_default_app(account)
        # 确保发布后的应用有 token（get_token_with_default 会按需生成并提交）
        token = await self.app_service.get_token_with_default(app)
        return {
            "token": token,
            "name": app.name,
            "icon": app.icon,
            "id": str(app.id),
        }

    async def _first_published_app(self, account: Account) -> App | None:
        """账号下最近创建的已发布应用（未逻辑删除）。

        用 account_id（PG_UUID）过滤——create_app 只写 account_id，不写 created_by，
        用 created_by 会匹配不到 create_app 产出的应用，导致每次刷新都重复创建。
        """
        stmt = (
            select(App)
            .where(
                App.account_id == account.id,
                App.status == AppStatus.PUBLISHED.value,
                App.is_deleted.is_(False),
            )
            .order_by(desc(App.created_at))
        )
        return (await self.db.scalars(stmt)).first()

    async def _create_and_publish_default_app(self, account: Account) -> App:
        """创建 + 发布一个默认应用（独立事务边界），并刷新返回最新状态的应用。"""
        from internal.schema.app_schema import CreateAppReq

        ctx = get_request_context()
        scheme = (ctx.scheme or "http")
        host = (ctx.host or "localhost:5000")
        icon = f"{scheme}://{host}/default-app-icon"
        req = CreateAppReq(
            name=DEFAULT_PLUGIN_APP_NAME,
            icon=icon,
            description=DEFAULT_PLUGIN_APP_DESC,
            app_type="agent",
        )
        app = await self.app_service.create_app(req, account)
        await self.app_service.publish_draft_app_config(app.id, account)
        # 发布后刷新应用，确保拿到最新 status / token
        return await self.app_service.get_app(app.id, account)

    async def get_web_app(self, token: str) -> App:
        """根据传递的token获取WebApp实例"""
        # 在数据库中查询token对应的应用（过滤逻辑删除的应用）
        app = (await self.db.scalars(
            select(App).where(
                App.token == token,
                App.is_deleted.is_(False),
            )
        )).one_or_none()
        if app is None or app.status != AppStatus.PUBLISHED.value:
            raise NotFoundException("该WebApp不存在或者未发布，请核实后重试")

        return app

    async def get_web_app_info(self, token: str) -> dict[str, Any]:
        """根据传递的token获取WebApp信息"""
        # 1、获取App基础信息
        app = await self.get_web_app(token)

        # 2、根据App基础信息构建LLM
        app_config = await self.app_config_service.get_app_config(app)
        llm = await self.language_model_service.load_language_model(app_config.get("model_config", {}))

        # 3、提取信息并返回
        return {
            "id": str(app.id),
            "icon": app.icon,
            "name": app.name,
            "description": app.description,
            "app_config": {
                "opening_statement": app_config.get("opening_statement"),
                "opening_questions": app_config.get("opening_questions"),
                "suggested_after_answer": app_config.get("suggested_after_answer"),
                "features": llm.features,
                "text_to_speech": app_config.get("text_to_speech"),
                "speech_to_text": app_config.get("speech_to_text"),
                "dialog_round": app_config.get("dialog_round"),
            }
        }

    async def get_default_web_app(self, account: Account) -> dict[str, Any]:
        """获取当前账号的默认 WebApp（第一个已发布的、有 token 的应用）。

        供 Web 端 /web-apps（无 token）入口使用：没有 token 时自动落到一个可用应用，
        前端再据此跳转对应页面。无可用应用时抛 NotFoundException。
        """
        stmt = (
            select(App)
            .where(
                App.created_by == account.id,
                App.status == AppStatus.PUBLISHED.value,
                App.is_deleted.is_(False),
                App.token.is_not(None),
                App.token != "",
            )
            .order_by(desc(App.created_at))
        )
        app = (await self.db.scalars(stmt)).first()
        if app is None:
            raise NotFoundException("当前账号没有可用的已发布 WebApp，请先发布应用")
        return {
            "token": app.token,
            "name": app.name,
            "icon": app.icon,
            "id": str(app.id),
        }

    async def prepare_web_app_chat(self, token: str, req: WebAppChatReq, account: Account) -> dict:
        """SSE 前置准备：校验/建会话/建消息/画像在流开始前完成（异常 → JSON 业务错误）。"""
        # 1、获取WebApp应用并校验应用是否发布
        app = await self.get_web_app(token)

        # 2、检测是否传递了会话id，如果传递了需要校验会话的归属信息
        if req.conversation_id:
            conversation = await self.get(Conversation, req.conversation_id)
            if (
                    not conversation
                    or conversation.app_id != app.id
                    or conversation.invoke_from != InvokeFrom.WEB_APP.value
                    or conversation.created_by != account.id
                    or conversation.is_deleted is True
            ):
                raise ForbiddenException("该会话不存在，或者不属于当前应用/用户/调用方式")
        else:
            # 3、如果没传递conversation_id表示新会话，这时候需要创建一个会话
            conversation = await self.create(Conversation, app_id=app.id, name="New Conversation", invoke_from=InvokeFrom.WEB_APP, created_by=account.id, updated_by=account.id)

        app_config = await self.app_config_service.get_app_config(app)

        file_infos, attachments_text = await self.attachment_service.load_attachments(
            req.file_ids or [], account
        )
        message = await self.create(
            Message,
            app_id=app.id,
            conversation_id=conversation.id,
            invoke_from=InvokeFrom.WEB_APP,
            created_by=account.id,
            updated_by=account.id,
            query=req.query,
            image_urls=req.image_urls,
            file_urls=file_infos,
            status=MessageStatus.NORMAL,
        )
        # 附件文本注入 LLM（临时属性，不落库到 query；ChatRunner 读取）
        message.attachment_text = attachments_text
        # 3.1、透传恢复标记（临时属性，Message 模型无此列；ChatRunner 读取 resume_trigger 决定是否断点续跑）
        message.resume_trigger = req.resume
        # 3.2、透传被恢复的原始消息 id（断点按 message_id 定位；ChatRunner 注入编排器 state 用于读断点）
        message.resume_message_id = req.resume_message_id or None

        # 4、加载用户画像（语义记忆：当前有效事实 -> 画像文本；长期记忆未开启时不读取）
        user_profile = ""
        if app_config.get("long_term_memory", {}).get("enable"):
            provider = await self.memory_provider_resolver.resolve(app_config)
            user_profile = await provider.get_user_profile(
                app_config, app.id, account.id,
            )

        # Agent 循环前提交读事务（防 PG 空闲事务超时；chat_runner.run 内亦会提交）
        await self.db.commit()

        return {
            "app": app,
            "app_config": app_config,
            "conversation": conversation,
            "message": message,
            "user_profile": user_profile,
            # 对话模式：chat=纯聊天 / agent=智能体模式（chat_runner 按此注入工作区工具）
            "mode": req.mode,
            "project_root": (req.project_root or "").strip(),
            "local_tool_runtime": bool(getattr(req, "local_tool_runtime", False)),
        }

    def stream_web_app_chat(
            self,
            token: str,
            req: WebAppChatReq,
            account: Account,
            prepared: dict,
    ) -> AsyncGenerator:
        """SSE 流式（prepared 由 prepare_web_app_chat 产出；异常/落库由 chat_runner 兜底）。"""
        async def _stream():
            async for event in self.chat_runner.run(
                app=prepared["app"],
                app_config=prepared["app_config"],
                conversation=prepared["conversation"],
                message=prepared["message"],
                account=account,
                invoke_from=InvokeFrom.WEB_APP,
                user_profile=prepared["user_profile"],
                mode=prepared.get("mode", "chat"),
                project_root=prepared.get("project_root", ""),
                local_tool_runtime=prepared.get("local_tool_runtime", False),
            ):
                yield event

        return _stream()

    def stream_web_app_chat_resume(
            self,
            token: str,
            run_id: UUID,
            last_event_id: int,
            account: Account,
    ) -> AsyncGenerator:
        """断流后重连续传：按 Last-Event-ID 重放事件日志，再按游标跟读到终态。

        配合 SSE 的 `id: <seq>` 与插件断开后用 `Last-Event-ID` 重连，解决长连接被硬断后
        `local_tool_call` 事件丢失、服务器 `wait_for_tool_result` 只能超时的问题。

        这里**不再订阅队列**：客户端断开后队列由 ChatRunner 的接管者独占（一个队列只能
        有一个读者，抢着读会各拿到一半事件），新事件由接管者写进事件日志，本端点跟读日志。
        """
        async def _stream():
            run_id_s = str(run_id)
            # 落库归并器：断开前已发出的那批事件，原流在 GeneratorExit 解绕中没来得及写库，
            # 所以把日志里登记的 AgentThought 一起收进来，续传结束时一次性补落。
            merged: dict[str, AgentThought] = {}
            for thought in run_event_log.history_thoughts_after(run_id_s, last_event_id):
                merge_agent_thought(merged, thought)
            cursor = last_event_id
            persisted = False

            async def _deliver(frame: str) -> bool:
                """落库（若这帧是终态）后交给调用方 yield，返回该帧是否为终态。

                落库必须早于把 agent_end 交给客户端——那是"可以关连接"的信号，
                写在最后一个 yield 之后的话客户端一关就被 GeneratorExit 跳过（真机丢过 2361 字）。
                """
                nonlocal cursor, persisted
                seq, event = _parse_sse_frame(frame)
                cursor = max(cursor, seq)
                if event in _RESUME_TERMINAL_EVENT_NAMES and not persisted:
                    await self._persist_resumed_run(run_id, merged, account)
                    persisted = True
                return event in _RESUME_TERMINAL_EVENT_NAMES

            replay = run_event_log.history_after(run_id_s, last_event_id)
            logger.info(
                "[sse-resume] 客户端重连 run=%s last_event_id=%d 待重放帧数=%d 待补落事件=%d",
                run_id_s, last_event_id, len(replay), len(merged),
            )
            for frame in replay:
                terminal = await _deliver(frame)
                yield frame
                if terminal:
                    return

            async def _already_finished_frame() -> tuple[str, str] | None:
                """run 已到终态时造一帧 agent_end 收尾并带回状态，否则返回 None（还在跑）。"""
                state = await self._get_run_terminal_state(run_id)
                if state is None:
                    return None
                status, conv_id, msg_id = state
                thought = AgentThought(id=uuid4(), task_id=run_id, event=QueueEvent.AGENT_END)
                frame = agent_thought_to_sse_frame(
                    thought, conv_id, msg_id, run_id, max(cursor, last_event_id) + 1,
                )
                return frame, status

            # 跟读日志：新事件由断开接管者写进来，本端点不再碰队列
            deadline = time.monotonic() + _RESUME_POLL_TIMEOUT_SECONDS
            next_liveness_check = 0.0
            while time.monotonic() < deadline:
                frames = run_event_log.history_after(run_id_s, cursor)
                if frames:
                    for frame in frames:
                        terminal = await _deliver(frame)
                        yield frame
                        if terminal:
                            return
                    continue
                # 日志空了就去问 run 还活着吗：接管者跑完的最后一步正是清日志，所以
                # "没有新帧 + run 已终态" 表示再怎么等也不会有内容了。不查这一眼的后果
                # 是真机实测到的：重连拿到 200 后一个字没有，干挂到读超时。
                now = time.monotonic()
                if now >= next_liveness_check:
                    next_liveness_check = now + _RESUME_LIVENESS_CHECK_SECONDS
                    finished = await _already_finished_frame()
                    if finished is not None:
                        frame, status = finished
                        await _deliver(frame)
                        logger.info(
                            "[sse-resume] run=%s 已结束 status=%s，补发 agent_end 收流 重连后已送达帧数=%d",
                            run_id_s, status, cursor - last_event_id,
                        )
                        yield frame
                        return
                await asyncio.sleep(_RESUME_POLL_INTERVAL_SECONDS)
            if not persisted:
                # 轮询到超时仍没见终态：把手上收到的事件落库，别让它们白跑一趟
                logger.warning(
                    "[sse-resume] run=%s 跟读超时 %ds 仍无终态帧 已送达帧数=%d",
                    run_id_s, _RESUME_POLL_TIMEOUT_SECONDS, cursor - last_event_id,
                )
                await self._persist_resumed_run(run_id, merged, account)

        return _stream()

    async def _get_run_terminal_state(
            self, run_id: UUID,
    ) -> tuple[str, str, str] | None:
        """run 已到终态则返回 (status, conversation_id, message_id)，仍在进行中返回 None。

        run 行不存在也按终态处理：没有主体，续传再怎么等也不会有事件进来。
        """
        try:
            row = (await self.db.execute(
                select(AgentRun.status, AgentRun.conversation_id, AgentRun.message_id)
                .where(AgentRun.id == run_id)
            )).first()
        except Exception:
            logger.exception("[sse-resume] 查询 run 状态失败 run=%s", run_id)
            # 查不动就不自作主张收流：宁可让客户端走到超时，也别把还没跑完的轮次误判成结束
            return None
        if row is None:
            return ("", "", "")
        if row.status in TERMINAL_RUN_STATUSES:
            return (row.status, str(row.conversation_id or ""), str(row.message_id or ""))
        return None

    async def _persist_resumed_run(
            self, run_id: UUID, merged: dict[str, AgentThought], account: Account,
    ) -> None:
        """把续传收到的事件交给 ChatRunner 落库并终结 run；任何异常都不该影响已送达的流。"""
        try:
            if not merged:
                # 二次重连时缓冲已清空、队列已耗尽：没有新事件就别去碰库，
                # save_agent_thoughts 是纯 INSERT，空跑或重跑都会长出重复的推理过程行
                return
            run = await self.db.get(AgentRun, run_id)
            if run is None:
                logger.warning("[sse-resume] 落库跳过：run 不存在 run=%s", run_id)
                return
            await self.chat_runner.persist_resumed_run(
                run=run, thoughts=list(merged.values()), account=account,
            )
        except Exception:
            logger.exception("[sse-resume] 落库异常 run=%s", run_id)

    async def web_app_chat(self, token: str, req: WebAppChatReq, account: Account) -> AsyncGenerator:
        """根据传递的token凭证+请求与指定的WebApp进行对话（async 生成器，产出 SSE 事件字符串）

        先 await prepare_web_app_chat（前置校验在流开始前，异常 → JSON 业务错误），再流式。
        """
        prepared = await self.prepare_web_app_chat(token, req, account)
        async for event in self.stream_web_app_chat(token, req, account, prepared):
            yield event

    async def stop_web_app_chat(self, token: str, task_id: UUID, account: Account):
        """根据传递的token+task_id停止与指定WebApp对话"""
        # 1、获取WebApp应用并校验应用是否发布
        await self.get_web_app(token)

        # 2、调用智能体队列管理器停止特定任务
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.WEB_APP, account.id)

    async def get_conversations(self, token: str, is_pinned: bool, account: Account) -> list[Conversation]:
        """根据传递的token+is_pinned+account获取指定账号在该WebApp下的会话列表数据"""
        # 1、获取WebApp应用并校验应用是否发布
        app = await self.get_web_app(token)

        # 2、筛选过滤并查询数据
        stmt = (
            select(Conversation)
            .where(
                Conversation.app_id == app.id,
                Conversation.created_by == account.id,
                Conversation.invoke_from == InvokeFrom.WEB_APP,
                Conversation.is_pinned == is_pinned,
                Conversation.is_deleted.is_(False),
            )
            .order_by(desc(Conversation.created_at))
        )
        conversations = (await self.db.execute(stmt)).scalars().all()

        return conversations

    async def update_conversation_settings(
            self,
            token: str,
            conversation_id: UUID,
            dialog_round: int | None,
            account: Account,
    ) -> Conversation:
        """更新WebApp会话设置（短期记忆窗口轮数，会话级覆盖）

        归属校验与 prepare_web_app_chat 一致：会话必须属于该应用 + WEB_APP 调用方式 + 当前账号。
        """
        app = await self.get_web_app(token)
        conversation = await self.get(Conversation, conversation_id)
        if (
                not conversation
                or conversation.app_id != app.id
                or conversation.invoke_from != InvokeFrom.WEB_APP.value
                or conversation.created_by != account.id
                or conversation.is_deleted is True
        ):
            raise ForbiddenException("该会话不存在，或者不属于当前应用/用户/调用方式")

        await self.update(conversation, dialog_round=dialog_round)
        return conversation

    async def code_action(self, token: str, req: CodeActionReq, account: Account) -> dict[str, Any]:
        """编辑器选中代码的 AI 操作（优化/解释/注释）：直接调用 LLM，不建会话、不入库。

        与 web_app_chat 的区别：
        - 不走 ChatRunner/Agent 流程（无检索、无记忆、无工具调用），响应快且稳定；
        - 不创建会话/消息记录（避免右键操作污染聊天历史）；
        - 返回纯结果 {code, explanation}：optimize/comment 返回可替换的 code，
          explain 返回 explanation 文本。
        """
        # 1、校验应用存在且已发布（与 chat 一致）
        app = await self.get_web_app(token)

        # 2、加载该应用配置的模型（与 get_web_app_info 一致；custom_api 按账号懒合并需 account_id）
        app_config = await self.app_config_service.get_app_config(app)
        llm = await self.language_model_service.load_language_model(
            app_config.get("model_config", {}), account_id=account.id
        )
        llm.temperature = 0.2

        # 3、按 action 构造提示词并调用
        language = (req.language or "").strip() or "代码"
        system_template = CODE_ACTION_TEMPLATES[req.action]
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            ("human", "语言: {language}\n选中代码:\n```\n{code}\n```"),
        ])
        chain = prompt | llm | StrOutputParser()
        raw = await _infer(chain.invoke, {
            "language": language,
            "code": req.code,
        })
        raw = (raw or "").strip()

        # 4、抽取代码块：模型可能返回 ```...``` 包裹，去掉围栏只留内容（优化/注释场景）
        code, explanation = _split_code_result(raw, req.action)
        return {
            "code": code,
            "explanation": explanation,
        }


# ===== 编辑器代码操作（code_action） =====

# optimize/comment 要求只输出代码本身，便于直接替换选中内容；
# explain 输出解释文本（不替换）。
CODE_ACTION_TEMPLATES: dict[str, str] = {
    "optimize": (
        "你是资深软件工程师。请优化用户选中的代码片段："
        "提升可读性、性能与健壮性，保持原有功能语义不变。"
        "只输出优化后的完整代码，不要任何解释、前后缀或 markdown 代码块围栏。"
    ),
    "comment": (
        "你是资深软件工程师。请为用户选中的代码片段添加清晰的中文注释："
        "解释每个函数/关键逻辑的作用。"
        "只输出添加注释后的完整代码，不要任何解释、前后缀或 markdown 代码块围栏。"
    ),
    "explain": (
        "你是资深软件工程师。请解释用户选中的代码片段："
        "这段代码做什么、关键逻辑如何工作、有哪些潜在问题或改进建议。"
        "用中文回答，条理清晰，不要输出代码。"
    ),
}

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n(.*?)^```\s*$", re.DOTALL | re.MULTILINE)


def _split_code_result(raw: str, action: str) -> tuple[str, str]:
    """从 LLM 原始输出中拆分 code / explanation。

    - optimize/comment：期望返回代码。若带 ``` 围栏则剥掉；多余的解释文本忽略。
    - explain：整段都是解释文本。
    """
    if action == "explain":
        return "", raw
    m = _CODE_FENCE_RE.search(raw)
    if m:
        return m.group(1).strip(), ""
    return raw, ""


def _infer(sync_fn, *args):
    """同步模型调用经线程池桥接（与 language_model_service 一致，避免跨 loop 死锁）。"""
    import asyncio
    return asyncio.to_thread(sync_fn, *args)
