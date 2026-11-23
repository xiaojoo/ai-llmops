#!/usr/bin/env python
"""
@Time    : 2026/1/18 18:01
@Author  : sunxiaojie
@File    : assistant_agent_service.py
"""
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from internal.config.settings import get_settings
from internal.core.agent.agents import FunctionCallAgent
from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
from internal.core.agent.entities.agent_entity import AgentConfig, create_ask_user_tool
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Account, Conversation, Message
from internal.schema.assistant_agent_schema import (
    AssistantAgentChat,
    GetAssistantAgentMessagesWithPageReq,
)
from internal.task.app_task import auto_create_app
from package.paginator import Paginator

from .attachment_service import AttachmentService
from .base_service import BaseService
from .chroma_service import ChromaService
from .conversation_service import ConversationService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)


@dataclass
class AssistantAgentService(BaseService):
    """辅助智能体服务"""
    db: AsyncSession
    chroma_service: ChromaService
    conversation_service: ConversationService
    language_model_service: LanguageModelService
    attachment_service: AttachmentService

    async def prepare_assistant_chat(self, req: AssistantAgentChat, account: Account) -> dict:
        """SSE 前置准备：校验/建消息/建 Agent 在流开始前完成，Agent 循环前提交读事务。"""
        # 1、获取辅助Agent对应的id
        assistant_agent_id = get_settings().assistant_agent_id

        # 2、获取当前应用调试会话信息
        conversation = await self._get_or_create_assistant_agent_conversation(account)

        # 3、解析附件文件：文本内容注入LLM，元信息落库供历史展示
        raw_query = req.query
        file_infos, attachments_text = await self.attachment_service.load_attachments(
            req.file_ids or [], account
        )

        # 4、新建消息
        message = await self.create(
            Message,
            app_id=assistant_agent_id,
            conversation_id=conversation.id,
            created_by=account.id,
            updated_by=account.id,
            query=raw_query,
            image_urls=req.image_urls,
            file_urls=file_infos,
            status=MessageStatus.NORMAL,
        )

        # 5、LLM（静态 qwen provider，带 account_id 行为不变；custom_api 按账号懒合并需 account_id）
        llm = await self.language_model_service.load_language_model({
            "provider": "qwen3_5-plus",
            "model": "qwen3.7-plus",
            "parameters": {
                "temperature": 0.8
            }
        }, account_id=account.id)
        # 6、短期记忆（async 版 TokenBufferMemory）
        token_buffer_memory = TokenBufferMemory(
            db=self.db,
            conversation=conversation,
            model_instance=llm,
        )
        history = await token_buffer_memory.get_history_prompt_messages(
            message_limit=3
        )

        # 7、工具
        tools = [
            self.chroma_service.convert_chroma_to_tool(),
            self.convert_create_app_to_tool(account.id),
            create_ask_user_tool(),
        ]

        # 8、Agent & 队列
        agent = FunctionCallAgent(
            name="call-agent",
            llm=llm,
            agent_config=AgentConfig(
                user_id=account.id,
                invoke_from=InvokeFrom.ASSISTANT_AGENT,
                enable_long_term_memory=True,
                tools=tools,
            )
        )

        # 9、Agent 循环前提交读事务（防 PG 空闲事务超时杀连接）
        await self.db.commit()

        # 10、将附件文本拼接到提问中，使模型可以读取文件内容
        llm_query = raw_query
        if attachments_text:
            llm_query = f"{raw_query}\n\n[附件内容]\n{attachments_text}"

        return {
            "assistant_agent_id": assistant_agent_id,
            "conversation": conversation,
            "message": message,
            "llm": llm,
            "agent": agent,
            "history": history,
            "llm_query": llm_query,
        }

    def stream_assistant_chat(
            self,
            req: AssistantAgentChat,
            account: Account,
            prepared: dict,
    ) -> AsyncGenerator:
        """SSE 流式：LLM 异常转 ERROR SSE 事件，finally 落库推理过程。"""
        async def _stream():
            from package.response import sse_format

            conversation = prepared["conversation"]
            message = prepared["message"]
            llm = prepared["llm"]
            agent = prepared["agent"]
            history = prepared["history"]
            llm_query = prepared["llm_query"]
            assistant_agent_id = prepared["assistant_agent_id"]
            agent_thoughts = {}
            seq = 0

            try:
                # agent.stream 是同步生成器，用 _aiter_sync 增量桥接（每事件经线程池 next()），
                # 避免 list() 物化全部事件导致流式语义丢失（SSE 被缓冲）。
                from internal.service.chat_runner import _aiter_sync
                async for agent_thought in _aiter_sync(agent.stream({
                    "messages": [llm.convert_to_human_message(llm_query, req.image_urls)],
                    "history": history,
                    "long_term_memory": conversation.summary if conversation.summary else "",
                })):
                    event_id = str(agent_thought.id)

                    # 9、将数据填充到agent_thought，便于存储到数据库服务中
                    if agent_thought.event != QueueEvent.PING:
                        if agent_thought.event == QueueEvent.AGENT_MESSAGE:
                            if event_id not in agent_thoughts:
                                agent_thoughts[event_id] = agent_thought
                            else:
                                # 10、叠加智能体消息
                                agent_thoughts[event_id] = agent_thoughts[event_id].model_copy(update={
                                    "thought": agent_thoughts[event_id].thought + agent_thought.thought,
                                    # 消息相关字段
                                    "message": agent_thought.message,
                                    "message_token_count": agent_thought.message_token_count,
                                    "message_unit_price": agent_thought.message_unit_price,
                                    "message_price_unit": agent_thought.message_price_unit,
                                    # 答案相关字段
                                    "answer_token_count": agent_thought.answer_token_count,
                                    "answer_unit_price": agent_thought.answer_unit_price,
                                    "answer_price_unit": agent_thought.answer_price_unit,
                                    # Agent推理统计相关
                                    "total_token_count": agent_thought.total_token_count,
                                    "total_price": agent_thought.total_price,
                                    "answer": agent_thoughts[event_id].answer + agent_thought.answer,
                                    "latency": agent_thought.latency,
                                })
                        else:
                            agent_thoughts[event_id] = agent_thought
                    data = {
                        **agent_thought.model_dump(include={
                            "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                            "total_token_count", "total_price", "trace",
                            "question", "options", "allow_custom", "choice", "sub_task_options",
                        }),
                        "id": event_id,
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                        "task_id": str(agent_thought.task_id),
                    }
                    seq += 1
                    yield sse_format(agent_thought.event.value, data, seq)
            except Exception as e:
                # LLM 异常 → ERROR SSE 事件
                logger.exception(f"辅助Agent推理过程发生异常，conversation_id={conversation.id}")
                error_thought = AgentThought(
                    id=uuid4(), task_id=uuid4(), event=QueueEvent.ERROR,
                    observation=f"推理过程发生异常：{e}",
                )
                agent_thoughts[str(error_thought.id)] = error_thought
                data = {
                    **error_thought.model_dump(include={
                        "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                        "total_token_count", "total_price", "trace",
                        "question", "options", "allow_custom", "choice", "sub_task_options",
                    }),
                    "id": str(error_thought.id),
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "task_id": str(error_thought.task_id),
                }
                seq += 1
                yield sse_format(QueueEvent.ERROR.value, data, seq)
            finally:
                # 将消息以及推理过程添加到数据库（含 ERROR 事件；失败仅记日志不阻断流）
                if agent_thoughts:
                    try:
                        await self.conversation_service.save_agent_thoughts(
                            account_id=account.id,
                            app_id=assistant_agent_id,
                            app_config={"long_term_memory": {"enable": True}},
                            conversation_id=conversation.id,
                            message_id=message.id,
                            agent_thoughts=list(agent_thoughts.values()),
                        )
                    except Exception:
                        logger.exception(f"保存辅助Agent推理过程失败，conversation_id={conversation.id}")

        return _stream()

    async def chat(self, req: AssistantAgentChat, account: Account) -> AsyncGenerator:
        """传递query与账号实现与辅助Agent进行会话（先 prepare 再流式）。"""
        prepared = await self.prepare_assistant_chat(req, account)
        async for event in self.stream_assistant_chat(req, account, prepared):
            yield event

    @classmethod
    def stop_chat(cls, task_id: UUID, account: Account) -> None:
        """根据传递的任务id+账号停止某次响应会话"""
        AgentQueueManager.set_stop_flag(task_id, InvokeFrom.ASSISTANT_AGENT, account.id)

    async def _get_or_create_assistant_agent_conversation(self, account: Account) -> Conversation:
        """按 id 查询辅助 Agent 会话，缺失时创建（独立事务边界）。"""
        conversation = (
            await self.db.get(Conversation, account.assistant_agent_conversation_id)
            if account.assistant_agent_conversation_id
            else None
        )
        if conversation is None:
            conversation = Conversation(
                app_id=get_settings().assistant_agent_id,
                name="New Conversation",
                invoke_from=InvokeFrom.ASSISTANT_AGENT,
                created_by=account.id,
                updated_by=account.id,
            )
            self.db.add(conversation)
            await self.db.flush()
            account.assistant_agent_conversation_id = conversation.id
            await self.db.commit()  # 独立事务边界
        return conversation

    async def get_conversation_messages_with_page(
            self,
            req: GetAssistantAgentMessagesWithPageReq,
            account: Account
    ) -> tuple[list[Message], Paginator]:
        """根据传递的请求+账号获取与辅助Agent对话的消息分页列表"""
        # 1、获取应用的调试会话
        conversation = await self._get_or_create_assistant_agent_conversation(account)

        # 2、构建分页器并构建游标条件
        paginator = Paginator(db=self.db, req=req)
        filters = []
        if req.created_at:
            # 3、将时间戳转换成DateTime
            created_at_datetime = datetime.fromtimestamp(req.created_at)
            filters.append(Message.created_at <= created_at_datetime)

        # 4、执行分页并查询数据
        stmt = (
            select(Message)
            .options(joinedload(Message.agent_thoughts))
            .where(
                Message.conversation_id == conversation.id,
                Message.status.in_([MessageStatus.STOP, MessageStatus.NORMAL]),
                Message.answer != "",
                *filters,
            )
            .order_by(desc(Message.created_at))
        )
        messages = await paginator.paginate(stmt)

        return messages, paginator

    async def delete_conversation(self, account: Account) -> None:
        """根据传递的账号，清空辅助Agent智能体会话消息列表"""
        await self.update(account, assistant_agent_conversation_id=None)

    @classmethod
    def convert_create_app_to_tool(cls, account_id: UUID) -> BaseTool:
        """定义自动创建Agent应用LangChain工具"""

        class CreateAppInput(BaseModel):
            """创建Agent/应用输入结构"""
            name: str = Field(description="需要创建的Agent/应用名称，长度不超过50个字符")
            description: str = Field(description="需要创建的Agent/应用描述，请详细概括该应用的功能")

        @tool("create_app", args_schema=CreateAppInput)
        def create_app(name: str, description: str) -> str:
            """如果用户提出了需要创建一个Agent/应用，你可以调用此工具，参数的输入是应用的名称+描述，返回的数据是创建后的成功di地址"""
            # 1、调用celery异步任务在后端创建应用
            auto_create_app.delay(name, description, account_id)

            # 2、返回成功提示
            return f"已调用后端异步任务创建Agent应用。\n应用名称: {name}\n应用描述: {description}"

        return create_app
