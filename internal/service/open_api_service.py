#!/usr/bin/env python
"""
@Time    : 2026/1/21 20:50
@Author  : sunxiaojie
@File    : open_api_service.py
"""
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.agent.agents import FunctionCallAgent, ReACTAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.entity.app_entity import AppStatus
from internal.entity.conversation_entity import InvokeFrom, MessageStatus
from internal.entity.dataset_entity import RetrievalSource
from internal.exception import ForbiddenException, NotFoundException
from internal.memory.token_buffer_memory import TokenBufferMemory
from internal.model import Account, Conversation, EndUser, Message
from internal.schema.open_api_schema import OpenAIChatReq
from package.response import Response

from .app_config_service import AppConfigService
from .app_service import AppService
from .base_service import BaseService
from .chat_runner import _aiter_sync
from .conversation_service import ConversationService

logger = logging.getLogger(__name__)
from .language_model_service import LanguageModelService
from .retrieval_service import RetrievalService

# 同步模型调用经线程池桥接
async def _infer(sync_fn, *args):
    """同步模型调用经线程池桥接。"""
    import asyncio
    return await asyncio.to_thread(sync_fn, *args)


@dataclass
class OpenAPIService(BaseService):
    """开放API服务"""
    db: AsyncSession
    app_service: AppService
    app_config_service: AppConfigService
    retrieval_service: RetrievalService
    conversation_service: ConversationService
    language_model_service: LanguageModelService

    async def chat(self, req: OpenAIChatReq, account: Account):
        """根据传递的请求+账号信息发起聊天对话，返回数据为块内容或者生成器"""
        # 1. 判断当前应用是否属于当前账号
        app = await self.app_service.get_app(req.app_id, account)

        # 2. 判断当前应用是否已发布
        if app.status != AppStatus.PUBLISHED.value:
            raise NotFoundException("该应用不存在或未发布，请核实后重试")

        # 3. 判断是否传递了终端用户id，如果传递了则检测终端用户关联的应用
        if req.end_user_id:
            end_user = await self.get(EndUser, req.end_user_id)
            if end_user is None or end_user.app_id != app.id:
                raise ForbiddenException("当前账号不存在或不属于该应用，请核实后重试")
        else:
            # 4. 如果不存在则创建一个终端用户
            end_user = await self.create(
                EndUser,
                tenant_id=account.id, app_id=app.id,
            )
        # 5. 检测是否传递了会话id，如果传递了需要检测会话的归属信息
        if req.conversation_id:
            conversation = await self.get(Conversation, req.conversation_id)
            if (
                    conversation is None
                    or conversation.app_id != app.id
                    or conversation.invoke_from != InvokeFrom.SERVICE_API.value
                    or conversation.created_by != end_user.id
            ):
                raise ForbiddenException("该会话不存在，或者不属于该应用/终端用户/调用方式")
        else:
            # 6. 如果不存在则创建会话信息
            conversation = await self.create(Conversation, app_id=app.id, name="New Conversation", invoke_from=InvokeFrom.SERVICE_API, created_by=end_user.id, updated_by=end_user.id)
        # 7. 获取校验后的运行时配置
        app_config = await self.app_config_service.get_app_config(app)

        # 8. 新建一条消息记录
        message = await self.create(Message, app_id=app.id, conversation_id=conversation.id, invoke_from=InvokeFrom.SERVICE_API, created_by=end_user.id, updated_by=end_user.id, query=req.query, image_urls=req.image_urls, status=MessageStatus.NORMAL)

        # 9. 根据传递的Model_config创建LLM实例（custom_api 按账号懒合并需 account_id）
        llm = await self.language_model_service.load_language_model(
            app_config.get("model_config", {}), account_id=account.id
        )

        # 10. 实例化TokenizerMemory用于提取短期记忆
        token_buffer_memory = TokenBufferMemory(
            db=self.db,
            conversation=conversation,
            model_instance=llm,
        )
        history = await token_buffer_memory.get_history_prompt_messages(
            message_limit=app_config["dialog_round"]
        )

        # 11. 将草稿配置中的tooLs转换成LangChain工具（按账号二次校验归属）
        tools = await self.app_config_service.get_langchain_tools_by_tools_config(
            app_config["tools"], account_id=account.id
        )

        # 12. 检测是否关联知识库
        if app_config["datasets"]:
            dataset_tool = await self.retrieval_service.create_langchain_tool_from_search(
                dataset_ids=[d["id"] for d in app_config["datasets"]],
                account_id=account.id,
                retrieval_score=RetrievalSource.APP,
                **app_config["retrieval_config"],
            )
            tools.append(dataset_tool)

        # 检测是否关联工作流，如果关联了工作流则将工作流构建成工具添加到tools中
        if app_config["workflows"]:
            workflow_tools = await self.app_config_service.get_langchain_tools_by_workflow_ids(
                [workflow["id"] for workflow in app_config["workflows"]],
                account_id=account.id,
            )
            tools.extend(workflow_tools)

        # 13、根据LLM是否支持tool_call决定使用不同的Agent
        agent_class = FunctionCallAgent if ModelFeature.TOOL_CALL in llm.features else ReACTAgent
        agent = agent_class(
            name="chat-agent",
            llm=llm,
            agent_config=AgentConfig(
                # Agent 归属终端用户而非租户账号，invoke_from=SERVICE_API
                user_id=end_user.id,
                invoke_from=InvokeFrom.SERVICE_API,
                max_iteration_count=app_config.get("max_iteration_count", 30),
                preset_prompt=app_config["preset_prompt"],
                enable_long_term_memory=app_config["long_term_memory"]["enable"],
                tools=tools,
                review_config=app_config["review_config"],
            )
        )

        # Agent 循环前提交读事务——LLM 调用可能耗时 60s+，空闲读事务会被 PG
        # idle_in_transaction_session_timeout 终止（对齐 chat_runner.py:190）。
        await self.db.commit()

        # 14. 定义智能体状态基础数据
        agent_state = {
            "messages": [llm.convert_to_human_message(req.query, req.image_urls)],
            "history": history,
            "long_term_memory": conversation.summary if conversation.summary else "",
        }

        # 15. 根据stream类型差异执行不同的代码
        account_id = account.id
        app_id = app.id
        conversation_id = str(conversation.id)
        message_id = str(message.id)
        end_user_id = str(end_user.id)
        if req.stream is True:
            agent_thoughts_dict = {}

            async def handle_stream() -> AsyncGenerator:
                from package.response import sse_format

                # try/except/finally——LLM 异常转 ERROR SSE 事件，finally 落库（含 ERROR）
                seq = 0
                try:
                    # agent.stream 为同步生成器（内部已起图线程 + Redis 队列监听），
                    # 经 _aiter_sync 逐元素线程池桥接，事件循环不阻塞
                    async for agent_thought in _aiter_sync(agent.stream(agent_state)):
                        event_id = str(agent_thought.id)

                        # 16. 将数据填充到agent_thought，便于存储到数据库服务中
                        if agent_thought.event != QueueEvent.PING:
                            if agent_thought.event == QueueEvent.AGENT_MESSAGE:
                                if event_id not in agent_thoughts_dict:
                                    agent_thoughts_dict[event_id] = agent_thought
                                else:
                                    # 17. 叠加智能体消息
                                    agent_thoughts_dict[event_id] = agent_thoughts_dict[event_id].model_copy(update={
                                        "thought": agent_thoughts_dict[event_id].thought + agent_thought.thought,
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
                                        "answer": agent_thoughts_dict[event_id].answer + agent_thought.answer,
                                        "latency": agent_thought.latency,
                                    })
                            else:
                                agent_thoughts_dict[event_id] = agent_thought
                        data = {
                            **agent_thought.model_dump(include={
                                "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                                "trace",
                            }),
                            "id": event_id,
                            "end_user_id": end_user_id,
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "task_id": str(agent_thought.task_id),
                        }
                        seq += 1
                        yield sse_format(agent_thought.event.value, data, seq)
                except Exception as e:
                    # LLM 异常 → ERROR SSE 事件（不再裸抛导致流悬挂/500）
                    logger.exception(f"OpenAPI 推理过程发生异常，conversation_id={conversation_id}")
                    error_thought = AgentThought(
                        id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.ERROR,
                        observation=f"推理过程发生异常：{e}",
                    )
                    agent_thoughts_dict[str(error_thought.id)] = error_thought
                    data = {
                        **error_thought.model_dump(include={
                            "event", "thought", "observation", "tool", "tool_input", "answer", "latency",
                            "trace",
                        }),
                        "id": str(error_thought.id),
                        "end_user_id": end_user_id,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "task_id": str(error_thought.task_id),
                    }
                    seq += 1
                    yield sse_format(QueueEvent.ERROR.value, data, seq)
                finally:
                    if agent_thoughts_dict:
                        try:
                            await self.conversation_service.save_agent_thoughts(
                                account_id=account_id,
                                app_id=app_id,
                                app_config=app_config,
                                conversation_id=conversation_id,
                                message_id=message_id,
                                agent_thoughts=[t for t in agent_thoughts_dict.values()],
                            )
                        except Exception:
                            logger.exception(f"保存 OpenAPI 推理过程失败，conversation_id={conversation_id}")

            return handle_stream()

        # 18. 块内容输出（agent.invoke 为同步推理，线程池桥接）
        agent_result = await _infer(agent.invoke, agent_state)

        # 19、将消息以及推理过程添加到数据库
        await self.conversation_service.save_agent_thoughts(
            account_id=account.id,
            app_id=app.id,
            app_config=app_config,
            conversation_id=conversation.id,
            message_id=message.id,
            agent_thoughts=agent_result.agent_thoughts,
        )

        # 返回真实 token 消耗与创建时间；event 统一为 .value
        total_tokens = sum(t.total_token_count or 0 for t in agent_result.agent_thoughts)
        return Response(data={
            "id": str(message.id),
            "end_user_id": str(end_user.id),
            "conversation_id": str(conversation.id),
            "query": req.query,
            "answer": agent_result.answer,
            "total_token_count": total_tokens,
            "latency": agent_result.latency,
            "created_at": int(message.created_at.timestamp()) if message.created_at else 0,
            "agent_thoughts": [
                {
                    "id": str(agent_thought.id),
                    "event": agent_thought.event.value if isinstance(agent_thought.event, QueueEvent) else agent_thought.event,
                    "model_name": agent_thought.model_name,
                    "thought": agent_thought.thought,
                    "observation": agent_thought.observation,
                    "llm_output": agent_thought.llm_output,
                    "tool_calls": agent_thought.tool_calls,
                    "message": agent_thought.message,
                    "tool": agent_thought.tool,
                    "tool_input": agent_thought.tool_input,
                    "trace": agent_thought.trace,
                    "latency": agent_thought.latency,
                    "created_at": 0,
                }
                for agent_thought in agent_result.agent_thoughts
            ],
        })
