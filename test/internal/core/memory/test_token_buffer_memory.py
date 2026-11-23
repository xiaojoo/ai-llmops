#!/usr/bin/env python
"""internal/core/memory TokenBufferMemory（DeepSeek 安全版本）async 化测试。

与 internal/memory 版本不同：按消息条数取历史（status 含 TIMEOUT），不过滤 is_archived。
"""
from uuid import uuid4

import pytest

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.core.memory.token_buffer_memory import TokenBufferMemory
from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message


class WindowLLM(BaseLanguageModel):
    def get_num_tokens(self, text: str) -> int:
        return len(text.encode("utf-8"))

    # langchain BaseLanguageModel 抽象方法：测试不实际调用
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_get_history_prompt_messages_returns_recent_window(db_session):
    """按 message_limit 返回最近 N 轮历史（倒序查询后反转，Human/AI 交替）"""
    from datetime import datetime, timedelta

    llm = WindowLLM(context_window=32768)
    user_id = uuid4()
    app_id = uuid4()

    conv = Conversation(
        app_id=app_id, created_by=user_id, updated_by=user_id,
        name="测试会话", invoke_from="debugger",
    )
    db_session.add(conv)
    await db_session.flush()

    base = datetime(2026, 8, 1, 12, 0, 0)
    for i in range(5):
        db_session.add(Message(
            app_id=app_id, conversation_id=conv.id,
            created_by=user_id, updated_by=user_id,
            invoke_from="debugger",
            query=f"问题{i}", answer=f"答案{i}",
            status=MessageStatus.NORMAL,
            # created_at 显式递增：同事务批量插入下默认时间戳可能相同，ORDER BY 需确定性
            created_at=base + timedelta(minutes=i),
        ))
    await db_session.flush()

    memory = TokenBufferMemory(db=db_session, conversation=conv, model_instance=llm)
    history = await memory.get_history_prompt_messages(message_limit=2)

    # 最近 2 轮：问题3/答案3 + 问题4/答案4（Human/AI 交替，时间升序）
    texts = [m.content for m in history]
    assert texts == ["问题3", "答案3", "问题4", "答案4"]
    assert "问题0" not in texts


@pytest.mark.asyncio
async def test_history_excludes_disliked_messages(db_session):
    """点踩（feedback=dislike）的消息不进入短期记忆"""
    from datetime import datetime, timedelta

    llm = WindowLLM(context_window=32768)
    user_id = uuid4()
    app_id = uuid4()

    conv = Conversation(
        app_id=app_id, created_by=user_id, updated_by=user_id,
        name="测试会话", invoke_from="debugger",
    )
    db_session.add(conv)
    await db_session.flush()

    base = datetime(2026, 8, 1, 12, 0, 0)
    for i in range(4):
        db_session.add(Message(
            app_id=app_id, conversation_id=conv.id,
            created_by=user_id, updated_by=user_id,
            invoke_from="debugger",
            query=f"问题{i}", answer=f"答案{i}",
            status=MessageStatus.NORMAL,
            feedback="dislike" if i == 2 else "",
            created_at=base + timedelta(minutes=i),
        ))
    await db_session.flush()

    memory = TokenBufferMemory(db=db_session, conversation=conv, model_instance=llm)
    history = await memory.get_history_prompt_messages(message_limit=10)

    texts = [m.content for m in history]
    assert "问题2" not in texts and "答案2" not in texts, "点踩消息不应进入短期记忆"
    assert "问题3" in texts and "答案3" in texts, "其余消息正常进入"


@pytest.mark.asyncio
async def test_history_always_includes_liked_messages(db_session):
    """点赞（feedback=like）的消息即使超出轮数窗口也一定进入短期记忆"""
    from datetime import datetime, timedelta

    llm = WindowLLM(context_window=32768)
    user_id = uuid4()
    app_id = uuid4()

    conv = Conversation(
        app_id=app_id, created_by=user_id, updated_by=user_id,
        name="测试会话", invoke_from="debugger",
    )
    db_session.add(conv)
    await db_session.flush()

    base = datetime(2026, 8, 1, 12, 0, 0)
    for i in range(5):
        db_session.add(Message(
            app_id=app_id, conversation_id=conv.id,
            created_by=user_id, updated_by=user_id,
            invoke_from="debugger",
            query=f"问题{i}", answer=f"答案{i}",
            status=MessageStatus.NORMAL,
            feedback="like" if i == 0 else "",
            created_at=base + timedelta(minutes=i),
        ))
    await db_session.flush()

    memory = TokenBufferMemory(db=db_session, conversation=conv, model_instance=llm)
    history = await memory.get_history_prompt_messages(message_limit=2)

    texts = [m.content for m in history]
    # 窗口只取最近 2 轮，但点赞的第 1 轮也必须保留，且按时间升序
    assert "问题0" in texts and "答案0" in texts, "点赞消息即使超出轮数窗口也一定进入短期记忆"
    assert "问题4" in texts and "答案4" in texts, "最近窗口消息正常保留"
    assert texts.index("问题0") < texts.index("问题4"), "历史应按时间升序排列"
