import uuid

from internal.core.agent.entities.agent_entity import ASK_USER_TOOL_NAME, create_ask_user_tool
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.service.conversation_service import ConversationService


def test_ask_user_tool_injected_when_tool_call():
    """ask_user 工具定义可被注入：name 正确、schema 完整（纯函数级验证）"""
    tool = create_ask_user_tool()
    assert tool.name == ASK_USER_TOOL_NAME
    props = tool.args_schema.schema()["properties"]
    assert {"question", "options", "allow_custom"} <= set(props)


def test_ask_user_event_in_save_list():
    """save_agent_thoughts 的保存事件列表必须包含 ASK_USER（读取源确认）"""
    import inspect
    from internal.service import conversation_service as cs
    src = inspect.getsource(cs.ConversationService.save_agent_thoughts)
    assert "QueueEvent.ASK_USER" in src


def test_ask_user_sub_task_options_in_sse_include():
    """chat_runner 的 model_dump include 必须包含 sub_task_options（读取源确认）"""
    import inspect
    from internal.service import chat_runner as cr
    src = inspect.getsource(cr.ChatRunner._stream_and_persist)
    assert '"sub_task_options"' in src
