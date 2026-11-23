#!/usr/bin/env python
"""
@Time    : 2025/12/12 21:41
@Author  : sunxiaojie
@File    : conversation_service.py
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Thread
from typing import Any
from uuid import UUID

from anyio import to_thread
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import build_structured_output_llm
from internal.entity.conversation_entity import (
    CONVERSATION_TEMPLATE,
    LIVE_RUN_STATUSES,
    LIVE_RUN_VISIBLE_SECONDS,
    SUGGESTED_QUESTIONS_TEMPLATE,
    SUMMARIZER_TEMPLATE,
    ConversationInfo,
    InvokeFrom,
    MessageStatus,
    SuggestedQuestions,
)
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Account, AgentRun, Conversation, Message, MessageAgentThought
from package.database import build_engine, worker_run
from package.paginator import Paginator

from internal.exception import NotFoundException
from internal.schema.conversation_schema import GetConversationMessagesWithPageReq
from .base_service import BaseService
from .language_model_service import LanguageModelService
from .reflection_service import ReflectionService

logger = logging.getLogger(__name__)

# 同步调用经 asyncio.to_thread 桥接（loop 默认执行器，避免跨 loop 死锁）。
async def _infer(sync_fn, *args):
    """同步模型调用（langchain 链 invoke）经线程池桥接。"""
    import asyncio
    return await asyncio.to_thread(sync_fn, *args)



@dataclass
class ConversationService(BaseService):
    """会话服务"""
    db: AsyncSession
    language_model_service: LanguageModelService
    reflection_service: ReflectionService

    async def is_conversation_new(self, conversation: Conversation, db: AsyncSession) -> bool:
        """判断会话是否为新建会话（消息数不超过 1 条）"""
        stmt = select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        message_count = await db.scalar(stmt) or 0
        return message_count <= 1

    async def get_message_conversation(self, message: Message, db: AsyncSession) -> Conversation | None:
        """获取消息所属的会话记录"""
        return await db.get(Conversation, message.conversation_id)

    async def summary(self, human_message: str, ai_message: str, old_summary: str = "") -> str:
        """根据传递的人类信息、AI消息还有原始的摘要信息总结生成一段新的摘要"""
        # 1、创建prompt
        prompt = ChatPromptTemplate.from_template(SUMMARIZER_TEMPLATE)

        # 2、构建大语言模型实例（走模型管理器，避免硬编码模型与API Key），将温度调低降低幻觉
        llm = await self.language_model_service.load_default_language_model()
        llm.temperature = 0.5

        # 3、构建链应用
        summary_chain = prompt | llm | StrOutputParser()

        # 4、调用链并获取新摘要信息
        new_summary = await _infer(summary_chain.invoke, {
            "summary": old_summary,
            "new_lines": f"Human:{human_message}\nAI：{ai_message}",
        })
        return new_summary

    async def compact_if_needed(
            self,
            conversation_id: UUID,
            llm,
            *,
            budget_ratio: float = 0.6,
    ) -> bool:
        """窗口 token 超过预算阈值时，把最旧轮次归档并入滚动摘要（惰性压缩）。

        预算 = 模型上下文窗口推导出的历史预算（复用 TokenBufferMemory._derive_max_token_limit）。
        返回是否发生了压缩。
        """
        # 1、读取窗口内（未归档）消息，按时间升序（最旧在前）
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.answer != "",
                Message.is_deleted.is_(False),
                Message.is_archived.is_(False),
                Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP]),
            )
            .order_by(Message.created_at.asc())
        )
        window_messages = (await self.db.execute(stmt)).scalars().all()
        if not window_messages:
            return False

        # 2、估算窗口 token（每轮 = Human + AI 两条消息）
        prompt_messages = []
        for message in window_messages:
            prompt_messages.extend([
                llm.convert_to_human_message(message.query, message.image_urls),
                AIMessage(
                    content=message.answer,
                    additional_kwargs=(
                        {"reasoning_content": message.reasoning_content}
                        if getattr(message, "reasoning_content", "")
                        else {}
                    ),
                ),
            ])
        window_tokens = llm.get_num_tokens_safe(prompt_messages) or 0

        # 3、推导预算（复用 TokenBufferMemory 的预算公式，保证可测试）
        memory = TokenBufferMemory(
            db=self.db,
            conversation=await self.get(Conversation, conversation_id),
            model_instance=llm,
        )
        budget = memory._derive_max_token_limit()
        if window_tokens <= budget * budget_ratio:
            return False

        # 4、归档顺序：先归档点踩消息（尽快离开短期记忆窗口），再从最旧开始归档其余消息；
        #    点赞消息永不归档（一定留在短期记忆窗口）。
        conversation = await self.get(Conversation, conversation_id)
        archived_lines = []
        remaining_tokens = window_tokens
        archived_any = False

        # 4.1 优先归档点踩消息（不受时间顺序限制；点踩内容不进长期记忆摘要）
        for message in window_messages:
            if remaining_tokens <= budget * budget_ratio:
                break
            if message.feedback != "dislike":
                continue
            msg_tokens = (
                llm.get_num_tokens_safe([
                    llm.convert_to_human_message(message.query, message.image_urls),
                    AIMessage(
                    content=message.answer,
                    additional_kwargs=(
                        {"reasoning_content": message.reasoning_content}
                        if getattr(message, "reasoning_content", "")
                        else {}
                    ),
                ),
                ]) or 0
            )
            await self.update(message, is_archived=True)
            remaining_tokens -= msg_tokens
            archived_any = True

        # 4.2 从最旧开始归档其余消息（点赞跳过，永不归档）
        for message in window_messages:
            if remaining_tokens <= budget * budget_ratio:
                break
            if message.feedback in ("like", "dislike"):
                continue
            msg_tokens = (
                llm.get_num_tokens_safe([
                    llm.convert_to_human_message(message.query, message.image_urls),
                    AIMessage(
                    content=message.answer,
                    additional_kwargs=(
                        {"reasoning_content": message.reasoning_content}
                        if getattr(message, "reasoning_content", "")
                        else {}
                    ),
                ),
                ]) or 0
            )
            await self.update(message, is_archived=True)
            archived_lines.append(f"Human:{message.query}\nAI：{message.answer}")
            remaining_tokens -= msg_tokens
            archived_any = True

        # 5、将归档轮次滚动进摘要（点踩已排除；点赞内容由点赞动作单独滚入）
        if archived_lines:
            new_lines = "\n".join(archived_lines)
            new_summary = await self._summarize(conversation.summary, new_lines)
            await self.update(conversation, summary=new_summary)
        return archived_any

    async def _summarize(self, old_summary: str, new_lines: str) -> str:
        """调用摘要模型生成滚动摘要（old_summary + 新归档内容 -> 新摘要）"""
        from internal.entity.conversation_entity import SUMMARIZER_TEMPLATE
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(SUMMARIZER_TEMPLATE)
        llm = await self.language_model_service.load_default_language_model()
        llm.temperature = 0.5
        chain = prompt | llm | StrOutputParser()
        return await _infer(chain.invoke, {"summary": old_summary, "new_lines": new_lines})

    async def generate_conversation_name(self, query: str) -> str:
        """根据传递的query生成对应的会话名字，并且语言与用户的输入保持一致"""
        # 1、创建prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", CONVERSATION_TEMPLATE),
            ("human", f"{query}")
        ])

        # 2、构建大语言模型实例（走模型管理器，避免硬编码模型与API Key），将温度调低降低幻觉概率
        llm = await self.language_model_service.load_default_language_model()
        llm.temperature = 0
        structured_llm = build_structured_output_llm(llm, ConversationInfo)

        # 3、构建链应用
        chain = prompt | structured_llm

        # 4、提取并整理query，截取长度过长的部分
        if len(query) > 2000:
            query = query[:300] + "...[TRUNCATED]..." + query[300:]
        query = query.replace("\n", " ")

        # 5、提取会话名称
        name = "新的会话"
        try:
            conversation_info = await _infer(chain.invoke, {"query": query, })

            if conversation_info and hasattr(conversation_info, "subject"):
                name = conversation_info.subject
        except Exception:
            logger.exception("提取会话名称出错：%(error)s")
        if len(name) > 75:
            name = name[:75] + "..."

        return name

    async def generate_suggested_questions(self, histories: str) -> list[str]:
        """根据传递的历史信息生成最多不超过3个的建议问题"""
        # 1、创建prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", SUGGESTED_QUESTIONS_TEMPLATE),
            ("human", "{histories}")
        ])

        # 2、构建大语言模型实例（走模型管理器，避免硬编码模型与API Key），将温度调低降低幻觉概率
        llm = await self.language_model_service.load_default_language_model()
        llm.temperature = 0
        structured_llm = build_structured_output_llm(llm, SuggestedQuestions)

        # 3、构建链应用
        chain = prompt | structured_llm

        # 4、提取建议问题列表
        questions = []
        try:
            suggested_questions = await _infer(chain.invoke, {"histories": histories, })

            if suggested_questions and hasattr(suggested_questions, "questions"):
                questions = suggested_questions.questions
        except Exception:
            logger.exception("提取建议问题列表出错：%(error)s")
        if len(questions) > 3:
            questions = questions[:3]

        return questions

    async def save_agent_thoughts(
            self,
            account_id: UUID,
            app_id: UUID,
            app_config: dict[str, Any],
            conversation_id: UUID,
            message_id: UUID,
            agent_thoughts: list[AgentThought],
            invoke_from: InvokeFrom = InvokeFrom.DEBUGGER,
    ) -> None:
        """存储智能体推理步骤信息"""
        position = 0
        latency = 0

        # 在子线程中重新查询conversation以及message，确保对象会被子线程的会话管理到
        conversation = await self.get(Conversation, conversation_id)
        message = await self.get(Message, message_id)
        if conversation is None or message is None:
            logger.warning(
                "保存推理过程失败：会话或消息不存在, conversation_id=%s, message_id=%s",
                conversation_id, message_id,
            )
            return

        # 循环遍历所有的智能体推理过程执行存储操作
        for agent_thought in agent_thoughts:
            # 存储长期记忆召回、推理、消息、动作、知识库检索等步骤
            if agent_thought.event in [
                QueueEvent.LONG_TERM_MEMORY_RECALL,
                QueueEvent.AGENT_THOUGHT,
                QueueEvent.AGENT_MESSAGE,
                QueueEvent.AGENT_ACTION,
                QueueEvent.DATASET_RETRIEVAL,
                QueueEvent.SUB_TASK_PLAN,
                QueueEvent.SUB_TASK_START,
                QueueEvent.SUB_TASK_END,
                QueueEvent.ASK_USER,
            ]:
                position += 1
                latency += agent_thought.latency
                await self.create(
                    MessageAgentThought,
                    app_id=app_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    invoke_from=invoke_from,
                    created_by=account_id,
                    updated_by=account_id,
                    position=position,
                    event=agent_thought.event,
                    model_name=agent_thought.model_name,
                    thought=agent_thought.thought,
                    observation=agent_thought.choice or agent_thought.observation,
                    llm_output=agent_thought.llm_output,
                    tool_calls=agent_thought.tool_calls,
                    tool=agent_thought.tool,
                    tool_input=agent_thought.tool_input,
                    trace=agent_thought.trace,
                    message=agent_thought.message,
                    message_token_count=agent_thought.message_token_count,
                    message_unit_price=agent_thought.message_unit_price,
                    message_price_unit=agent_thought.message_price_unit,
                    answer=agent_thought.answer,
                    answer_token_count=agent_thought.answer_token_count,
                    answer_unit_price=agent_thought.answer_unit_price,
                    answer_price_unit=agent_thought.answer_price_unit,
                    total_token_count=agent_thought.total_token_count,
                    total_price=agent_thought.total_price,
                    latency=agent_thought.latency,
                    sub_task_id=agent_thought.sub_task_id,
                    sub_task_title=agent_thought.sub_task_title,
                    task_id=agent_thought.task_id,
                )

            if agent_thought.event == QueueEvent.AGENT_MESSAGE:
                await self.update(
                    message,
                    message=agent_thought.message,
                    # 消息相关字段
                    message_token_count=agent_thought.message_token_count,
                    message_unit_price=agent_thought.message_unit_price,
                    message_price_unit=agent_thought.message_price_unit,
                    # 答案相关字段
                    answer=agent_thought.answer,
                    reasoning_content=agent_thought.reasoning_content,
                    answer_token_count=agent_thought.answer_token_count,
                    answer_unit_price=agent_thought.answer_unit_price,
                    answer_price_unit=agent_thought.answer_price_unit,
                    # Agent推理统计相关
                    total_token_count=agent_thought.total_token_count,
                    total_price=agent_thought.total_price,
                    latency=latency,
                )
                # 检测是否开启长期记忆
                if app_config["long_term_memory"]["enable"]:
                    Thread(
                        target=self._generate_summary_and_update,
                        kwargs={
                            "conversation_id": conversation.id,
                            "query": message.query,
                            "answer": agent_thought.answer,
                        }
                    ).start()

                # 处理生成新会话名称
                if await self.is_conversation_new(conversation, self.db):
                    Thread(
                        target=self._generate_conversation_name_and_update,
                        kwargs={
                            "conversation_id": conversation.id,
                            "query": message.query,
                        }
                    ).start()

            # 判断是否为停止获取错误，如果是则需要更新消息状态
            if agent_thought.event in [QueueEvent.TIMEOUT, QueueEvent.STOP, QueueEvent.ERROR]:
                await self.update(
                    message,
                    status=agent_thought.event,
                    error=agent_thought.observation,
                )
                break

    def _generate_summary_and_update(
            self,
            conversation_id: UUID,
            query: str,
            answer: str,
    ) -> None:
        """子线程生成会话摘要并更新"""
        from internal.container import create_conversation_service

        async def _coro(session: AsyncSession) -> None:
            service = create_conversation_service(session)
            # 1、根据id获取会话
            conversation = await service.get(Conversation, conversation_id)
            if conversation is None:
                logger.warning("生成摘要失败：会话不存在 conversation_id=%s", conversation_id)
                return
            # LLM 调用前先提交读事务——摘要生成可能耗时 60s+，避免事务空闲被 PG 终止
            await session.commit()
            # 2、计算会话新摘要信息
            new_summary = await service.summary(query, answer, conversation.summary)
            # 3、更新会话的摘要信息
            await service.update(conversation, summary=new_summary)

        # 线程内独立 loop 必须使用 build_engine——全局 engine 的 asyncpg 连接绑定主事件循环，
        # 跨 loop 复用会抛 InterfaceError 并毒化连接池。
        worker_run(_coro, commit_on_success=True, engine_factory=build_engine)

    def _generate_conversation_name_and_update(
            self,
            conversation_id: UUID,
            query: str
    ) -> None:
        """生成会话名字并更新"""
        from internal.container import create_conversation_service

        async def _coro(session: AsyncSession) -> None:
            service = create_conversation_service(session)
            # 1、根据会话id获取会话
            conversation = await service.get(Conversation, conversation_id)
            if conversation is None:
                logger.warning("生成会话名失败：会话不存在 conversation_id=%s", conversation_id)
                return
            # LLM 调用前先提交读事务
            await session.commit()
            # 2、计算获取新会话名字
            new_conversation_name = await service.generate_conversation_name(query)
            # 3、调用更新服务更新会话名称
            await service.update(conversation, name=new_conversation_name)

        worker_run(_coro, commit_on_success=True, engine_factory=build_engine)

    async def get_conversation(self, conversation_id: UUID, account: Account) -> Conversation:
        """根据传递的会话id+account，获取指定的会话信息"""
        # 1、根据conversation_id查询会话记录
        conversation = await self.get(Conversation, conversation_id)
        if (
                not conversation
                or conversation.created_by != account.id
                or conversation.is_deleted
        ):
            raise NotFoundException("该会话不存在获取已经删除，请核实后重试")

        return conversation

    async def get_conversation_messages_with_page(
            self,
            conversation_id: UUID,
            req: GetConversationMessagesWithPageReq,
            account: Account,
    ) -> tuple[list[Message], Paginator]:
        """根据传递的会话id+请求数据，获取当前账号下该会话的消息分页列表数据"""
        # 1、获取会话并校验权限
        conversation = await self.get_conversation(conversation_id, account)

        # 2、构建分页器并设置游标条件
        paginator = Paginator(db=self.db, req=req)
        filters = []
        if req.created_at:
            # 3. 将时间戳转换成DateTime
            created_at_datetime = datetime.fromtimestamp(req.created_at)
            filters.append(Message.created_at <= created_at_datetime)

        # 4、执行分页并查询数据
        # 仍在进行中（running / awaiting_input）的这一轮，answer 还没落库所以是空串，必须
        # 豁免下面"normal 且 answer 为空则隐藏"的规则：否则刷新后这条消息在列表里根本查不到，
        # 前端也就拿不到 run_id 去发起断流重连（真机实测踩到的正是这个）。
        # 时间窗，避免无人接手的孤儿 running run 复活成永久转圈的空消息。
        # 两个时钟坑（真机实测踩到）：
        #  1) created_at 由 DB 的 CURRENT_TIMESTAMP 写入，本机 DB 是 UTC 而 Python 是本地
        #     UTC+8，用 datetime.now() 比较会差 8 小时把全部行静默排除；故锚必须用服务端 now()。
        #  2) started_at 可空，NULL >= cutoff 恒为 NULL 同样会静默漏行，不用它。
        live_run_message_ids = (
            select(AgentRun.message_id)
            .where(
                AgentRun.status.in_(list(LIVE_RUN_STATUSES)),
                AgentRun.parent_run_id.is_(None),
                AgentRun.created_at >= func.now() - timedelta(seconds=LIVE_RUN_VISIBLE_SECONDS),
            )
        )
        stmt = (
            select(Message)
            .options(joinedload(Message.agent_thoughts))
            .where(
                Message.conversation_id == conversation.id,
                # 展示 normal（正常）/stop（用户停止）/timeout（超时）/error（异常）的消息——
                # 中断/超时/出错的任务也保留已输出内容和「继续执行」入口，避免已输出部分凭空消失。
                # normal 仍需 answer 非空（隐藏未完成的占位消息）；
                # 终态（stop/timeout/error）即使 answer 为空也展示——它们有运行轨迹（agent_thoughts）
                # 和/或续跑断点（sub_task_checkpoint），是"已发生过、可查看/可续跑"的完整一轮。
                Message.status.in_([
                    MessageStatus.NORMAL,
                    MessageStatus.STOP,
                    MessageStatus.TIMEOUT,
                    MessageStatus.ERROR,
                ]),
                or_(
                    Message.answer != "",
                    Message.status != MessageStatus.NORMAL,
                    Message.id.in_(live_run_message_ids),
                ),
                Message.is_deleted.is_(False),
                *filters,
            )
            .order_by(desc(Message.created_at))
        )
        messages = await paginator.paginate(stmt)

        # 5、标记每条消息是否可断点续跑（动态属性，Message 模型无 can_resume 列）
        # 仅 stop/timeout/error 状态消息才可能可恢复（EXISTS 查询避免 N+1）
        # 按 message_id 定位断点（不再依赖 query 字符串精确匹配——同一会话多轮消息的断点归属各自消息）
        # has_resumable_checkpoints 为 async 方法，漏 await 会让 can_resume 变成协程对象
        from .sub_task_service import SubTaskService
        sub_task_service = SubTaskService(db=self.db)
        for m in messages:
            m.can_resume = (
                m.status in (MessageStatus.STOP, MessageStatus.TIMEOUT, MessageStatus.ERROR)
                and await sub_task_service.has_resumable_checkpoints(m.id)
            )

        # 5.1、注入每条消息"最新 run"的终态（run_status）。
        # 消息列表无法仅凭 message.status 判断"是否还在运行"：超时(latest run timed_out)与
        # 真正运行中(running)都可能让消息带 status='timeout'/'running'。前端据此把已终结的消息
        # 从"运行中"误判里摘出来（运行中仍可点停止，终结的显示「继续执行」/只读）。
        from internal.entity.conversation_entity import RunStatus as _RunStatus

        message_ids = [m.id for m in messages]
        if message_ids:
            # 取每消息最新 version 的 run：仅需 status/id 两列，避免物化整行（ORDER BY version DESC 取首行）
            # run_id 一并透出：前端刷新后要按 run_id 调 /chat/{run_id}/resume 重挂还在跑的 run。
            run_rows = (
                await self.db.execute(
                    select(AgentRun.message_id, AgentRun.status, AgentRun.id)
                    .where(
                        AgentRun.message_id.in_(message_ids),
                        AgentRun.parent_run_id.is_(None),
                    )
                    .order_by(AgentRun.message_id, AgentRun.version.desc())
                )
            ).all()
            # 去重保留每消息首行（ORDER BY message_id, version DESC 后，首行即最新 run）
            latest_run_by_msg: dict = {}
            for message_id, run_status, run_id in run_rows:
                if message_id not in latest_run_by_msg:
                    latest_run_by_msg[message_id] = (run_status, run_id)
            for m in messages:
                latest = latest_run_by_msg.get(m.id)
                m.run_status = latest[0] if latest else ""
                m.run_id = str(latest[1]) if latest and latest[1] else ""

        return messages, paginator

    async def get_message(self, message_id: UUID, account: Account) -> Message:
        """根据传递的消息id+账号，获取指定的消息"""
        # 1、根据message_id查询消息记录
        message = await self.get(Message, message_id)
        if (
                not message
                or message.created_by != account.id
                or message.is_deleted
        ):
            raise NotFoundException("该消息不存在或被删除，请核实后重试")

        # 2、校验通过返回消息
        return message

    async def delete_conversation(self, conversation_id: UUID, account: Account) -> Conversation:
        """根据传递的会话id+账号删除指定的会话记录"""
        # 1、获取会话记录并校验权限
        conversation = await self.get_conversation(conversation_id, account)

        # 2、更新会话的删除状态
        await self.update(conversation, is_deleted=True)

        # 3、清理子任务断点（级联清理，失败不影响会话删除；断点按 message_id 归属，按会话清空该会话全部断点）
        try:
            from .sub_task_service import SubTaskService
            sub_task_service = SubTaskService(db=self.db)
            await sub_task_service.clear_checkpoints(conversation_id=conversation_id)
        except Exception:
            logger.exception("清理子任务断点失败 conversation_id=%s", conversation_id)

        return conversation

    async def delete_message(self, conversation_id: UUID, message_id: UUID, account: Account) -> Message:
        """根据传递的会话id+消息id删除指定的消息记录"""
        # 1、获取会话记录并校验权限
        conversation = await self.get_conversation(conversation_id, account)

        # 2、获取消息并校验权限
        message = await self.get_message(message_id, account)

        # 3、判断消息和会话是否关联
        if conversation.id != message.conversation_id:
            raise NotFoundException("该会话下不存在该消息，请核实后重试")

        # 4、校验通过修改消息is_deleted属性标记删除
        await self.update(message, is_deleted=True)

        # 5、清理该消息的子任务断点（级联清理，失败不影响消息删除；断点按 message_id 归属）
        try:
            from .sub_task_service import SubTaskService
            sub_task_service = SubTaskService(db=self.db)
            await sub_task_service.clear_checkpoints(message_id=message_id)
        except Exception:
            logger.exception("清理子任务断点失败 message_id=%s", message_id)

        return message

    async def update_conversation(self, conversation_id: UUID, account: Account, **kwargs) -> Conversation:
        """根据传递的会话id+账号+kwargs更新会话信息"""
        # 1、获取会话记录并校验权限
        conversation = await self.get_conversation(conversation_id, account)

        # 2、更新会话信息
        await self.update(conversation, **kwargs)

        return conversation

    async def update_message_feedback(
            self,
            conversation_id: UUID,
            message_id: UUID,
            feedback: str,
            account: Account,
    ) -> Message:
        """根据传递的会话id+消息id+反馈类型，更新指定消息的用户反馈（like/dislike/''）"""
        # 1、校验反馈类型
        if feedback not in ("like", "dislike", ""):
            from internal.exception import ValidateException
            raise ValidateException("反馈类型仅支持 like、dislike 或空字符串")

        # 2、获取会话与消息并校验权限归属
        conversation = await self.get_conversation(conversation_id, account)
        message = await self.get_message(message_id, account)

        # 3、判断消息和会话是否关联
        if conversation.id != message.conversation_id:
            raise NotFoundException("该会话下不存在该消息，请核实后重试")

        # 4、更新消息反馈
        await self.update(message, feedback=feedback)

        # 5、点赞：一定加入短期记忆（若已归档则解除归档回到窗口）+ 异步滚动进长期记忆（摘要）
        if feedback == "like" and message.answer:
            if message.is_archived:
                await self.update(message, is_archived=False)
            Thread(
                target=self._roll_liked_into_summary,
                kwargs={
                    "conversation_id": conversation.id,
                    "query": message.query,
                    "answer": message.answer,
                },
            ).start()

        # 6、feedback 为 dislike 时，异步触发行为反思（程序记忆改写）
        if feedback == "dislike" and message.answer:
            Thread(
                target=self._trigger_reflection,
                kwargs={
                    "app_id": message.app_id,
                    "user_id": message.created_by,
                    "query": message.query,
                    "answer": message.answer,
                },
            ).start()

        return message

    def _roll_liked_into_summary(
            self,
            *,
            conversation_id: UUID,
            query: str,
            answer: str,
    ) -> None:
        """子线程执行：把点赞轮次滚动进会话长期记忆（摘要），保证点赞内容一定进长期记忆"""
        from internal.container import create_conversation_service

        async def _coro(session: AsyncSession) -> None:
            service = create_conversation_service(session)
            # 1、根据id获取会话
            conversation = await service.get(Conversation, conversation_id)
            if conversation is None:
                logger.warning("点赞内容滚动进摘要失败：会话不存在 conversation_id=%s", conversation_id)
                return
            # LLM 调用前先提交读事务——摘要生成可能耗时，避免事务空闲被 PG 终止
            await session.commit()
            # 2、把点赞轮次滚动进会话摘要
            new_summary = await service._summarize(
                conversation.summary,
                f"Human:{query}\nAI：{answer}",
            )
            # 3、更新会话的摘要信息
            await service.update(conversation, summary=new_summary)

        # 线程内独立 loop 必须使用 build_engine——全局 engine 的 asyncpg 连接绑定主事件循环，
        # 跨 loop 复用会抛 InterfaceError 并毒化连接池。
        worker_run(_coro, commit_on_success=True, engine_factory=build_engine)

    def _trigger_reflection(
            self,
            *,
            app_id: UUID,
            user_id: UUID,
            query: str,
            answer: str,
    ) -> None:
        """子线程执行反馈反思（写程序记忆）"""
        from internal.container import create_reflection_service

        async def _coro(session: AsyncSession) -> None:
            try:
                reflection_service = create_reflection_service(session)
                await reflection_service.reflect_on_feedback(
                    app_id=app_id, user_id=user_id,
                    query=query, answer=answer, feedback="dislike",
                )
            except Exception:
                logger.exception(
                    "反馈反思失败，app_id=%s, user_id=%s", app_id, user_id,
                )

        worker_run(_coro, commit_on_success=True, engine_factory=build_engine)
