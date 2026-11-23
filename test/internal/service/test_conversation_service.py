#!/usr/bin/env python
"""ConversationService async 化测试——摘要/命名走 LanguageModelService + 消息分页"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.model import Account, Conversation, Message
from internal.service import ConversationService


class FakeSummaryLLM:
    """记录输入并返回固定文本的假 LLM（可被 RunnableSequence 包装）"""
    temperature = 1.0

    def __init__(self, reply="摘要结果"):
        self.reply = reply
        self.invoked_inputs = []

    def __call__(self, inputs):
        """Runnable 协议：被 coerce_to_runnable 包装为 RunnableLambda 后由链调用"""
        self.invoked_inputs.append(inputs)
        return self.reply


def _svc(db=MagicMock()) -> ConversationService:
    return ConversationService(
        db=db,
        language_model_service=MagicMock(),
        reflection_service=MagicMock(),
    )


class TestConversationServiceSummary:
    @pytest.mark.asyncio
    async def test_summary_uses_language_model_service(self):
        service = _svc()
        fake_llm = FakeSummaryLLM("新摘要")

        service.language_model_service.load_default_language_model = AsyncMock(return_value=fake_llm)

        result = await service.summary("你好", "你好，有什么可以帮你？", "旧摘要")

        assert result == "新摘要"
        assert fake_llm.temperature == 0.5, "摘要模型温度应被设置为 0.5"
        # 说明：langchain-core 1.6.0 中 `prompt | llm` 链传给 LLM 的是渲染后的 ChatPromptValue
        # （而非模板变量 dict），因此这里校验旧摘要确实进入了 LLM 的模板输入，与 brief 断言意图一致
        prompt_value = fake_llm.invoked_inputs[0]
        assert "旧摘要" in prompt_value.to_string()


class TestGetConversationMessagesWithPage:
    @pytest.mark.asyncio
    async def test_messages_paginated_for_owner(self, db_session, monkeypatch):
        """消息分页：仅返回该会话下 answer 非空、未删除、normal/stop 状态的消息"""
        from internal.service.sub_task_service import SubTaskService

        # SubTaskService 仍同步，替身 has_resumable_checkpoints 返回 False（不触 Flask db）
        # 断点按 message_id 定位，签名 (self, message_id)
        monkeypatch.setattr(
            SubTaskService, "has_resumable_checkpoints",
            lambda self, message_id: False,
        )

        account = Account(name="t", email="t@t.com")
        db_session.add(account)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=account.id, updated_by=account.id,
            name="会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()
        for i in range(3):
            db_session.add(Message(
                app_id=conv.app_id, conversation_id=conv.id,
                created_by=account.id, updated_by=account.id,
                invoke_from="debugger", query=f"q{i}", answer=f"a{i}",
                status="normal",
            ))
        # 空 answer 的消息应被过滤（Message.answer != ""）
        db_session.add(Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            invoke_from="debugger", query="q3", answer="", status="normal",
        ))
        await db_session.flush()

        service = _svc(db=db_session)
        req = SimpleNamespace(
            current_page=1,
            page_size=10,
            created_at=None,
        )
        messages, paginator = await service.get_conversation_messages_with_page(conv.id, req, account)

        assert paginator.total_record == 3, "空 answer 消息应被过滤"
        assert len(messages) == 3
        assert paginator.total_page == 1
        assert {m.query for m in messages} == {"q0", "q1", "q2"}

    @pytest.mark.asyncio
    async def test_foreign_account_rejected(self, db_session):
        """权限校验：非创建者访问会话抛 NotFound"""
        from internal.exception import NotFoundException

        owner = Account(name="o", email="o@t.com")
        db_session.add(owner)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=owner.id, updated_by=owner.id,
            name="会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()

        service = _svc(db=db_session)
        req = SimpleNamespace(
            current_page=1,
            page_size=10,
            created_at=None,
        )
        with pytest.raises(NotFoundException):
            await service.get_conversation_messages_with_page(
                conv.id, req, MagicMock(id=uuid4())
            )

    @pytest.mark.asyncio
    async def test_can_resume_gated_by_message_checkpoints(self, db_session, monkeypatch):
        """断点按 message_id 定位：can_resume 只由该消息自身是否有可恢复断点决定。

        回归：同一会话内多轮编排消息，若按 (conversation_id, query) 共享断点键，
        不同 query 会互相覆盖/无法匹配，导致已停止消息的 can_resume 恒为 False、
        「继续执行」按钮不出现。按 message_id 后，停止消息只要保存过断点即可续跑。
        """
        from internal.service.sub_task_service import SubTaskService

        # 记录 has_resumable_checkpoints 收到的 message_id，并按 message_id 判断（模拟真实断点归属）
        received = []
        resumable_by_msg = {}

        async def _fake_has_resumable(self, message_id):
            received.append(message_id)
            return resumable_by_msg.get(message_id, False)

        monkeypatch.setattr(SubTaskService, "has_resumable_checkpoints", _fake_has_resumable)

        account = Account(name="t", email="t@t.com")
        db_session.add(account)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=account.id, updated_by=account.id,
            name="会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()

        # 会话内两轮消息，query 不同；已停止的那条按其 message_id 存有断点
        stopped = Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="任务A", answer="部分结果", status="stop",
        )
        other = Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="任务B", answer="结果B", status="normal",
        )
        db_session.add(stopped)
        db_session.add(other)
        await db_session.flush()
        resumable_by_msg[stopped.id] = True

        service = _svc(db=db_session)
        req = SimpleNamespace(current_page=1, page_size=10, created_at=None)
        messages, _ = await service.get_conversation_messages_with_page(conv.id, req, account)

        by_id = {m.id: m for m in messages}
        assert by_id[stopped.id].can_resume is True, "已停止且存在自身断点的消息应可续跑"
        assert by_id[other.id].can_resume is False, "正常消息不应可续跑"
        # 关键：以 message_id 查询，而非 conversation_id+query
        assert stopped.id in received

    @pytest.mark.asyncio
    async def test_timeout_and_error_messages_with_content_are_shown(self, db_session, monkeypatch):
        """回归：超时（timeout）/异常（error）消息不应被会话消息列表过滤掉。

        此前状态过滤仅含 [STOP, NORMAL]，导致超时/出错但已输出部分内容的消息从对话列表消失，
        「继续执行」也无法出现。现在应保留 timeout/error 且 answer 非空的消息。
        """
        from internal.service.sub_task_service import SubTaskService

        async def _fake_has_resumable(self, message_id):
            return False

        monkeypatch.setattr(SubTaskService, "has_resumable_checkpoints", _fake_has_resumable)

        account = Account(name="t", email="t@t.com")
        db_session.add(account)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=account.id, updated_by=account.id,
            name="会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()

        for status, answer, query in [
            ("normal", "完整回答", "q_normal"),
            ("stop", "停止时部分内容", "q_stop"),
            ("timeout", "超时前部分内容", "q_timeout"),
            ("error", "出错前部分内容", "q_error"),
            # 终态但 answer 为空：仍应展示——可能是编排子任务/断点中的一轮，需保留轨迹与续跑入口
            ("timeout", "", "q_timeout_empty"),
            ("stop", "", "q_stop_empty"),
        ]:
            db_session.add(Message(
                app_id=conv.app_id, conversation_id=conv.id,
                created_by=account.id, updated_by=account.id,
                query=query, answer=answer, status=status,
            ))
        # 正常消息但无内容：应继续被过滤（answer 为空、非终态）
        db_session.add(Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="q_normal_empty", answer="", status="normal",
        ))
        await db_session.flush()

        service = _svc(db=db_session)
        req = SimpleNamespace(current_page=1, page_size=20, created_at=None)
        messages, paginator = await service.get_conversation_messages_with_page(conv.id, req, account)

        shown = {m.query for m in messages}
        assert {"q_normal", "q_stop", "q_timeout", "q_error"} <= shown, \
            f"timeout/error 有内容的消息应保留，实际: {shown}"
        assert {"q_timeout_empty", "q_stop_empty"} <= shown, \
            f"终态(answer 空)的消息应保留，实际: {shown}"
        assert "q_normal_empty" not in shown, "正常但空 answer 的消息仍应被过滤"
        assert paginator.total_record == 6

    @pytest.mark.asyncio
    async def test_run_status_injected_from_latest_run(self, db_session, monkeypatch):
        """run_status 应注入该消息"最新 run"的终态；无 run 的消息 run_status=''。

        回归：前端无法仅凭 message.status 判断"是否还在运行"，需把 agent_run 终态
        （timed_out/cancelled/failed/succeeded）与真正运行中(running)区分开，
        否则已超时/已停止但 answer 为空的消息会被当作"运行中"永远转圈。
        """
        from internal.model import AgentRun
        from internal.service.sub_task_service import SubTaskService

        async def _fake_has_resumable(self, message_id):
            return False

        monkeypatch.setattr(SubTaskService, "has_resumable_checkpoints", _fake_has_resumable)

        account = Account(name="t", email="t@t.com")
        db_session.add(account)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=account.id, updated_by=account.id,
            name="会话", invoke_from="debugger",
        )
        db_session.add(conv)
        await db_session.flush()

        timed_out_msg = Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="超时任务", answer="", status="timeout",
        )
        running_msg = Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="运行中任务", answer="运行中输出", status="normal",
        )
        no_run_msg = Message(
            app_id=conv.app_id, conversation_id=conv.id,
            created_by=account.id, updated_by=account.id,
            query="无run任务", answer="普通输出", status="normal",
        )
        db_session.add(timed_out_msg)
        db_session.add(running_msg)
        db_session.add(no_run_msg)
        await db_session.flush()

        # timed_out_msg 有两个 run（v1 succeeded, v2 timed_out 最新）；running_msg 一个 run running
        old_run_id, latest_run_id, running_run_id = uuid4(), uuid4(), uuid4()
        db_session.add(AgentRun(
            id=old_run_id,
            app_id=conv.app_id, conversation_id=conv.id, message_id=timed_out_msg.id,
            created_by=account.id, updated_by=account.id, version=1,
            agent_type="orchestrator", status="succeeded",
        ))
        db_session.add(AgentRun(
            id=latest_run_id,
            app_id=conv.app_id, conversation_id=conv.id, message_id=timed_out_msg.id,
            created_by=account.id, updated_by=account.id, version=2,
            agent_type="orchestrator", status="timed_out",
        ))
        db_session.add(AgentRun(
            id=running_run_id,
            app_id=conv.app_id, conversation_id=conv.id, message_id=running_msg.id,
            created_by=account.id, updated_by=account.id, version=1,
            agent_type="orchestrator", status="running",
        ))
        await db_session.flush()

        service = _svc(db=db_session)
        req = SimpleNamespace(current_page=1, page_size=10, created_at=None)
        messages, _ = await service.get_conversation_messages_with_page(conv.id, req, account)
        by_id = {m.id: m for m in messages}
        assert by_id[timed_out_msg.id].run_status == "timed_out", \
            "应注入最新 run（version 最大）的终态"
        assert by_id[running_msg.id].run_status == "running", "运行中的 run 如实返回 running"

        # run_id 与 run_status 必须来自同一个"最新 run"：前端刷新后拿它调
        # /chat/{run_id}/resume 重挂，给错 version 就会连到一条已终结、事件缓冲已清空的 run。
        assert by_id[running_msg.id].run_id == str(running_run_id), \
            "running 消息要带回可重连的 run_id"
        assert by_id[timed_out_msg.id].run_id == str(latest_run_id), \
            "run_id 必须取 version 最大的那个 run，不能回落到 v1"
        assert by_id[no_run_msg.id].run_status == "", "无 run 的消息 run_status 为空"
        assert by_id[no_run_msg.id].run_id == "", "无 run 的消息 run_id 为空"

    @pytest.mark.asyncio
    async def test_in_flight_message_visible_only_while_run_live(self, db_session, monkeypatch):
        """正在生成的那轮（status=normal 且 answer 仍为空）必须出现在消息列表里。

        真机实测踩到的坑：列表过滤规则是"normal 且 answer 为空则隐藏"，而断流重连要找的
        恰恰就是这条消息——它被过滤掉时前端刷新后什么都看不到，run_id 也无从取。
        同时约束时间窗：无人接手、终态没人落的孤儿 running run 不该复活成永久转圈的空消息。
        """
        from datetime import datetime

        from internal.model import AgentRun
        from internal.service.sub_task_service import SubTaskService

        async def _fake_has_resumable(self, message_id):
            return False

        monkeypatch.setattr(SubTaskService, "has_resumable_checkpoints", _fake_has_resumable)

        account = Account(name="t2", email="t2@t.com")
        db_session.add(account)
        await db_session.flush()
        conv = Conversation(
            app_id=uuid4(), created_by=account.id, updated_by=account.id,
            name="会话", invoke_from="web_app",
        )
        db_session.add(conv)
        await db_session.flush()

        def _new_message(tag: str) -> Message:
            m = Message(
                app_id=conv.app_id, conversation_id=conv.id,
                created_by=account.id, updated_by=account.id,
                query=f"提问-{tag}", answer="", status="normal",
            )
            db_session.add(m)
            return m

        live_msg = _new_message("live")
        stale_msg = _new_message("stale")
        await db_session.flush()

        # live 行故意不传 created_at，交给 DB 的 CURRENT_TIMESTAMP 写：本库 DB 是 UTC、
        # Python 本地是 UTC+8，若实现误用 datetime.now() 做窗口比较，这一行会被差 8 小时
        # 的时钟排除掉，本用例就会红——即时区 bug 的直接判据。
        db_session.add(AgentRun(
            app_id=conv.app_id, conversation_id=conv.id, message_id=live_msg.id,
            created_by=account.id, updated_by=account.id, version=1,
            status="running",
        ))
        # stale 行用一个远早于任何时钟的时间，避免依赖 UTC/本地的相对差
        db_session.add(AgentRun(
            app_id=conv.app_id, conversation_id=conv.id, message_id=stale_msg.id,
            created_by=account.id, updated_by=account.id, version=1,
            status="running", created_at=datetime(2020, 1, 1),
        ))
        await db_session.flush()

        service = _svc(db=db_session)
        req = SimpleNamespace(current_page=1, page_size=20, created_at=None)
        messages, _ = await service.get_conversation_messages_with_page(conv.id, req, account)
        shown = {m.query for m in messages}

        assert "提问-live" in shown, (
            "还在跑的那轮被列表过滤挡掉 → 刷新后前端找不到消息、拿不到 run_id，重连无从发起"
        )
        assert "提问-stale" not in shown, "超出时间窗的孤儿 running run 不该复活成空气泡消息"
        live_row = next(m for m in messages if m.query == "提问-live")
        assert live_row.run_status == "running" and live_row.run_id, (
            "可见的同时必须带上 run_id，前端才能直接调 resume 端点"
        )
