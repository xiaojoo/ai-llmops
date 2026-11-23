#!/usr/bin/env python
"""
@Time    : 2025/12/12 21:54
@Author  : sunxiaojie
@File    : conversation_entity.py
"""
from enum import Enum

from pydantic import BaseModel, Field

# 摘要汇总模版
SUMMARIZER_TEMPLATE = """逐步总结提供的对话内容，在之前的总结基础上继续添加并返回一个新的总结。

EXAMPLE
当前总结：
人类询问 AI 对人工智能的看法。AI 认为人工智能是一股向善的力量。

新的会话：
Human：为什么你认为人工智能是一股向善的力量？
AI：因为人工智能将帮助人类发挥他们全部的潜力。

新的总结：
人类询问AI对人工智能的看法，AI认为人工智能一股向善的力量，因为它将帮助人类发挥全部潜力。
END OF EXAMPLE

当前总结：
{summary}

新的会话：
{new_lines}

新的总结"""

# CONVERSATION_TEMPLATE = """请从用户传递的内容中提取出对应的主题
# {task_description}
#
# 请严格按照以下 JSON 格式输出：
# {format_instructions}"""

CONVERSATION_TEMPLATE = "请从用户传递的内容中提取出对应的主题"


class ConversationInfo(BaseModel):
    """你需要将用户的输入分解为”主题”和“意图”，以便准确识别用户输入的类型。
    注意：用户的语言可能是多样性的，可以是英文、中文、日语、法语等。
    确保你的输出与用户的语言尽可能一致并简短！

    示例1：
    用户输入: hi, my name is LiHua
    {
        "language_type": "用户的输入是存英文",
        "reasoning": "输出语言必须是英文",
        "subject": "Users greet me"
    }

    示例2：
    用户输入: hello
    {
        "language_type": "用户的输入是存英文",
        "reasoning": "输出语言必须是英文",
        "subject": "Greeting myself"
    }

    示例3：
    用户输入: www.apache.com讲了什么
    {
        "language_type": "用户输入是中英文混合",
        "reasoning": "英文部分是uRL，主要意图还是使用中文表达的，所以输出语言必须是中文",
        "subject": "询问网站www.apache.com"
    }

    示例4：
    用户输入: why小红的年龄is老than小明？
    {
        "language_type": "用户输入是中英文混合",
        "reasoning": "英文部分是口语化输入，主要意图是中文，且中文占据更大的实际意义，所以输出语言必须是中文",
        "subject": "询问小红和小明的年龄"
    }

    示例5：
    用户输入: yo, 你今天怎么样？
    {
        "language_type": "用户输入是中英文混合",
        "reasoning": "英文部分是口语化输入，主要意图是中文，所以输出语言必须是中文",
        "subject": "询问我今天的状态"
    }
    """
    language_type: str = Field(description="用户输入语言类型声明")
    reasoning: str = Field(description="对用户输入的文本进行语言判断的推理过程，类型为字符串")
    subject: str = Field(description=(
        "对用户的输入进行简短的总结，提取输入的“意图”和”主题”，"
        "输出语言必须和输入语言保持一致，尽可能简单明了，"
        "尤其是用户问题针对模型本身时，可以通过适当的方式加入趣味性。"
    ))


# 建议问题提示词模版
SUGGESTED_QUESTIONS_TEMPLATE = "请根据传递的历史信息预测人类最后可能会问的三个问题：{histories}"


class SuggestedQuestions(BaseModel):
    """请帮我预测人类最可能会问的三个问题，并且每个问题都保持在50个字符以内。
    生成的内容必须是指定模式的JS0N格式数组：[“问题1”，“问题2”，“问题3"]"""
    questions: list[str] = Field(description="建议问题列表，类型为字符串数组")


class InvokeFrom(str, Enum):
    """回话调用来源"""
    SERVICE_API = "service_api"  # 开发api服务调用
    WEB_APP = "web_app"  # web应用
    DEBUGGER = "debugger"  # 调试页面
    ASSISTANT_AGENT = "assistant_agent"  # 辅助Agent调用


class MessageStatus(str, Enum):
    """回话状态"""
    NORMAL = "normal"
    STOP = "stop"
    TIMEOUT = "timeout"
    ERROR = "error"


class RunStatus(str, Enum):
    """Agent 运行（run）状态：一次执行的完整生命周期状态机

    pending → running → (awaiting_input ⇄ running) → 终态 succeeded / failed / cancelled / timed_out
    Message.status 语义收窄为"该消息最新 run 状态的投影"（见 project_message_status）。
    """
    PENDING = "pending"          # 已创建、待调度
    RUNNING = "running"          # 图中执行中（含子任务在跑）
    AWAITING_INPUT = "awaiting_input"  # HITL 中断：确认点/ask_user 等待用户输入（不占线程）
    SUCCEEDED = "succeeded"      # 正常跑完（AGENT_END）
    FAILED = "failed"            # 图异常/模型错误/上下文超长
    CANCELLED = "cancelled"      # 用户 STOP / 编排器级联取消
    TIMED_OUT = "timed_out"      # 监听超时 / sub_task_timeout


def project_message_status(run_status: RunStatus) -> MessageStatus | None:
    """Run 状态 → Message 状态投影（收窄语义：message.status 是"最新 run 的视图"）。

    运行中/等待输入的 run 不投影（message 保持其既有状态，避免列表可见性跳动）；
    仅终态驱动 message.status。
    """
    mapping = {
        RunStatus.SUCCEEDED: MessageStatus.NORMAL,
        RunStatus.CANCELLED: MessageStatus.STOP,
        RunStatus.TIMED_OUT: MessageStatus.TIMEOUT,
        RunStatus.FAILED: MessageStatus.ERROR,
    }
    return mapping.get(run_status)


# 视为"这一轮还在进行中"的 run 状态。消息列表据此保留 answer 仍为空的占位消息：
# 否则"normal 且 answer 为空则隐藏"的规则会把正在生成/正在等用户输入的那条挡掉，
# 刷新后前端既看不到这条消息也拿不到 run_id，断流重连根本无从发起（真机实测踩到）。
LIVE_RUN_STATUSES = (RunStatus.RUNNING.value, RunStatus.AWAITING_INPUT.value)

# 占位消息的可见时间窗，与 AgentQueueManager 归属键 TTL（gen_task:belong ex=1800）同量级。
# 超过窗口还挂着 running 的是没人接手的孤儿 run（客户端断开后再没回来、终态无人落），
# 不该复活成一个永久转圈的空气泡；根治要靠脱离请求的持久化消费者。
LIVE_RUN_VISIBLE_SECONDS = 1800

# 这一轮已经不会再产生事件的 run 状态。续传端点据此收流：断开接管者跑完的最后一步就是
# 清事件日志，对着已清的日志空等到超时，等于让客户端挂一条永远没有结尾的长连接（真机实测踩到）。
TERMINAL_RUN_STATUSES = (
    RunStatus.SUCCEEDED.value, RunStatus.FAILED.value,
    RunStatus.CANCELLED.value, RunStatus.TIMED_OUT.value,
)
