import uuid

from internal.core.agent.entities.agent_entity import (
    ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE,
    ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE,
    SubTaskResult,
    SubTaskSpec,
    build_system_prompt,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent


def test_queue_event_has_sub_task_events():
    assert QueueEvent.SUB_TASK_PLAN == "sub_task_plan"
    assert QueueEvent.SUB_TASK_START == "sub_task_start"
    assert QueueEvent.SUB_TASK_END == "sub_task_end"


def test_agent_thought_sub_task_fields_default():
    thought = AgentThought(id=uuid.uuid4(), task_id=uuid.uuid4(), event=QueueEvent.AGENT_MESSAGE)
    assert thought.sub_task_id is None
    assert thought.sub_task_title == ""


def test_sub_task_spec_defaults():
    spec = SubTaskSpec(order=1, title="调研", role_prompt="你是调研员", expect_output="一份报告")
    assert spec.required_tools == []
    assert spec.task_id is None


def test_sub_task_result_defaults():
    result = SubTaskResult(order=1, title="调研")
    assert result.status == "normal"
    assert result.answer == ""
    assert result.resumed is False


def test_orchestrator_prompt_templates_exist():
    assert "{max_sub_tasks}" in ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE
    assert "{query}" in ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE
    assert "{sub_results_text}" in ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE
