from internal.core.agent.entities.agent_entity import (
    ASK_USER_TOOL_NAME,
    ASK_USER_WAIT_TIMEOUT,
    create_ask_user_tool,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent


def test_ask_user_event_value():
    assert QueueEvent.ASK_USER == "ask_user"


def test_agent_thought_ask_user_fields():
    thought = AgentThought(
        id="00000000-0000-0000-0000-000000000001",
        task_id="00000000-0000-0000-0000-000000000002",
        event=QueueEvent.ASK_USER,
        question="选择哪种授权模型？",
        options=["RBAC", "ABAC", "混合"],
        allow_custom=True,
        choice="混合",
    )
    assert thought.question == "选择哪种授权模型？"
    assert thought.options == ["RBAC", "ABAC", "混合"]
    assert thought.allow_custom is True
    assert thought.choice == "混合"
    assert thought.event == "ask_user"


def test_ask_user_tool_definition():
    tool = create_ask_user_tool()
    assert tool.name == ASK_USER_TOOL_NAME == "ask_user"
    assert ASK_USER_WAIT_TIMEOUT == 300
    schema = tool.args_schema.schema()
    assert "question" in schema["properties"]
    assert "options" in schema["properties"]
    assert "allow_custom" in schema["properties"]


from internal.core.agent.entities.agent_entity import ConfirmVerdict


def test_agent_thought_sub_task_options():
    thought = AgentThought(
        id="00000000-0000-0000-0000-000000000001",
        task_id="00000000-0000-0000-0000-000000000002",
        event=QueueEvent.ASK_USER,
        sub_task_options=[{"order": 1, "title": "检索资料", "role_prompt": "你是检索专家"}],
    )
    assert thought.sub_task_options == [{"order": 1, "title": "检索资料", "role_prompt": "你是检索专家"}]


def test_confirm_verdict_model():
    v = ConfirmVerdict()
    assert v.need_confirm is False
    assert v.reason == ""
    v2 = ConfirmVerdict(need_confirm=True, reason="存在歧义")
    assert v2.need_confirm is True
    assert v2.reason == "存在歧义"
