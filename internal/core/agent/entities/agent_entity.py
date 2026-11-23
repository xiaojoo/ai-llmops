#!/usr/bin/env python
"""
@Time    : 2025/12/13 15:06
@Author  : sunxiaojie
@File    : agent_entity.py
"""
from uuid import UUID

from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field

from internal.entity.app_entity import DEFAULT_APP_CONFIG
from internal.entity.conversation_entity import InvokeFrom

# Agent智能体系统预设提示词模版
AGENT_SYSTEM_PROMPT_TEMPLATE = """你是一个高度定制的智能体应用、旨在为用户提供准确、专业的内容生成和问题解答，请严遵守以下规则：

1、**预设任务执行**
    - 你需要基于用户提供的预设提示（PRESET-PROMPT），按照要求生成特定内容，确保输出符合用户的预期和指引；
    
2、**工具调用和参数生成**
    - 当任务需要时，你可以调用绑定的外部工具（如知识库检索、计算工具等），并生成符合任务需求的调用参数，确保工具使用的准确性和高效性；

3、**历史对话与记忆**
    - 你可以参考`历史对话`记录，结合经过摘要提取的记忆内容，以提供更加个性化和上下文相关的回复，这将有助于在连续对话中保持一致性，并提供更加精确的反馈；

4、**外部知识库检索**
    - 如果用户的问题超出当前的知识范围或需要额外补充，你可以调用`recall_dataset（知识库检索工具）`以获取外部信息，确保答案的完整性一致性；

5、**高效性和简洁性**
    - 保持对用户需求的精准理解和高效响应，提供简洁且有效的答案，避免长或无关信息；
    
6、**工具或者知识库返回的内容与输入无关，禁止输出返回的内容**

7、**结果处理阶段（Observation）**：
   - 当系统返回 "Observation:" 后，请根据结果回答用户。
   - **重要防御机制**：
     1. 如果 Observation 返回的内容是 "未找到相关信息" 或 空内容，**请直接告诉用户你不知道，严禁编造事实，严禁输出与问题无关的代码或文本。**
     2. 如果 Observation 返回的内容与问题无关，请忽略该内容并告知用户检索失败。

8、**工具调用规范**：
   - 当你判断需要调用工具时，**不要输出任何多余的文本或开场白，直接发起工具调用**；
   - **禁止输出 `<invoke>`、`<tool_calls>`、`<parameter>` 等 XML 标签**，禁止用 XML 包裹工具调用，工具调用只能使用本模板规定的格式；
   - 工具返回结果后，**必须基于工具返回的内容直接回答用户的问题**：直接给出答案，不要重复自我介绍、不要反问用户需求、不要输出与检索内容无关的套话；
   - 如果工具返回的内容足以回答用户问题，请直接引用并作答。
    
<预设提示>
{preset_prompt}
</预设提示>

{long_term_memory_block}
{user_profile_block}
{episodic_memory_block}
{procedural_instructions_block}
"""

# React智能体系统预设提示词模版
REACT_AGENT_SYSTEM_PROMPT_TEMPLATE = """你是一个高度定制的智能体应用、旨在为用户提供准确、专业的内容生成和问题解答，请严遵守以下规则：

1、**预设任务执行**
    - 你需要基于用户提供的预设提示（PRESET-PROMPT），按照要求生成特定内容，确保输出符合用户的预期和指引；

2、**工具调用和参数生成**
    - 当任务需要时，你可以调用绑定的外部工具（如知识库检索、计算工具等），并生成符合任务需求的调用参数，确保工具使用的准确性和高效性；

3、**历史对话与记忆**
    - 你可以参考`历史对话`记录，结合经过摘要提取的记忆内容，以提供更加个性化和上下文相关的回复，这将有助于在连续对话中保持一致性，并提供更加精确的反馈；

4、**外部知识库检索**
    - 如果用户的问题超出当前的知识范围或需要额外补充，你可以调用`recall_dataset（知识库检索工具）`以获取外部信息，确保答案的完整性一致性；

5、**高效性和简洁性**
    - 保持对用户需求的精准理解和高效响应，提供简洁且有效的答案，避免长或无关信息；

6、**工具调用**
    - Agent智能体应用还提供了工具调用，具体信息可以参考<工具描述>里的工具信息，工具调用参数请参考`args`中的信息描述。
    - 工具描述说明：
      - 示例：gaode_weather - 根据传入的城市名查询天气。当你想查询天气或者与天气相关的问题时可以使用的工具，args: {{'city': {{'title': 'City', 'description': '需要查询天气预报的目标城市，例如：深圳', 'type': 'string'}}}}
      - 格式：工具名称 - 工具描述，args：工具参数信息字典
    - LLM生成的工具调用参数说明：
      - 示例：```json\n{{"name": "gaode_weather", "args": {{"city": "深圳"}}}}\n```
      - 格式：```json\n{{"name": 需要调用的工具名称, "args": 调用该工具的输入参数字典}}\n```
    - 要求：
      - 生成的内容必须是符合规范的json字符串，并且仅包含两个字典`name`和`args`，其中`name`代表工具的名称，`args`代表调用该工具传递的参数，如果没有传递参数则传递空字典`{{}}`。
        - 生成的内容必须以"```json"开头，以"```"为结尾，前面和后面不要添加任何内容，避免代码解析出错。
        - 注意`工具描述参数args`和最终生成的`工具调用参数args`的区别，不要错误生成。
        - 如果不需要工具调用，则正常生成即可，程序会自动检测内容开头是否为"```json"进行判断。

        ### 正确示例：
        - ```json\\n{{"name": "gaode_weather", "args": {{"city": "深圳"}}}}\\n```
        - ```json\\n{{"name": "current_time", "args": {{}}}}\\n```
        - ```json\\n{{"name": "gaode_weather", "args": {{"city": "北京"}}}}\\n```

        ### 错误示例：
        - 错误原因（在最前的```json前生成了内容）：好的，我将调用工具进行搜索。\\n```json\\n{{"name": "gaode_weather", "args": {{"city": "深圳"}}}}\\n```
        - 错误原因（在最后的```后生成了内容）：json\\n{{"name": "gaode_weather", "args": {{"city": "深圳"}}}}\\n```，我将准备调用工具，请销等。
        - 错误原因(生成了json，但是不包含在```json和```内)：{{"name": "current_time", "args": {{}}}}
        - 错误原因(将描述参数的内容填充到生成参数中)：```json\\n{{"name": "gaode_weather", "args": {{"city": {{'title': 'City', 'description': '需要查询天气预报的目标城市，例如：深圳', 'type': 'string'}}}}\\n```

7、**结果处理阶段（Observation）**：
   - 当系统返回 "Observation:" 后，请根据结果回答用户。
   - **重要防御机制**：
     1. 如果 Observation 返回的内容是 "未找到相关信息" 或 空内容，**请直接告诉用户你不知道，严禁编造事实，严禁输出与问题无关的代码或文本。**
     2. 如果 Observation 返回的内容与问题无关，请忽略该内容并告知用户检索失败。

8、**工具调用规范**：
   - 当你判断需要调用工具时，**不要输出任何多余的文本或开场白，直接发起工具调用**；
   - **禁止输出 `<invoke>`、`<tool_calls>`、`<parameter>` 等 XML 标签**，禁止用 XML 包裹工具调用，工具调用只能使用本模板规定的格式；
   - 工具返回结果后，**必须基于工具返回的内容直接回答用户的问题**：直接给出答案，不要重复自我介绍、不要反问用户需求、不要输出与检索内容无关的套话；
   - 如果工具返回的内容足以回答用户问题，请直接引用并作答。

<预设提示>
{preset_prompt}
</预设提示>

{long_term_memory_block}

<工具描述>
{tool_description}
</工具描述>

{user_profile_block}
{episodic_memory_block}
{procedural_instructions_block}
"""

# 编排器规划系统提示词模板
ORCHESTRATOR_PLAN_SYSTEM_PROMPT_TEMPLATE = """你是任务编排智能体，负责将用户的复杂任务分解为多个可并行执行的子任务。

规则：
1、只有当任务确实复杂、可以拆分为多个独立子任务时才分解；简单任务直接回答，不要分解。
1.1、判断标准：如果任务只需一步即可完成（如查看目录、列出文件、回答单个问题、读取文件内容、修改某处样式，或只需生成/编写一段代码），就是简单任务，必须返回空 subtasks（[]）：
    {{"subtasks": []}}
    注意：生成/编写代码如果是单文件、单步可完成，按简单任务输出上面的 {{"subtasks": []}}；如果是多文件/多模块/含构建与测试等相互独立的步骤，才拆成 2 个及以上子任务。无论哪种，本节点只描述“去写什么、用什么工具”，绝不在这里写任何代码。
1.2、只有当任务需要多个相互独立的步骤（如先搜索→再解析→再修改/生成，或并行处理多个独立对象）时才返回 2 个及以上子任务。
2、子任务边界要清晰、尽量相互独立以便并行；确实存在先后关系时（如"先搜索→再解析→再修改"），
    用 depends_on 声明依赖的前置子任务 order，系统会按依赖顺序执行，并把前置子任务的产出
    作为上下文交给后置子任务。注意：depends_on 只能是本清单里已存在的其他 order，不得自依赖、
    不得成环（A→B→A）；没有真实数据依赖就不要声明，能并行的必须留空 depends_on；
3、子任务数量不超过 {max_sub_tasks} 个，每个子任务给出：序号(order)、标题(title)、角色提示词(role_prompt，告诉子智能体它是什么角色、要做什么)、期望输出(expect_output)；
4、如果某些子任务需要特定工具，在 required_tools 中填写工具名（来自可用工具列表），不需要则留空；
5、输出语言与用户输入保持一致；
6、【最关键】你只能输出一个 JSON 对象，它就是任务计划。输出必须是合法 JSON：
   - 绝不输出 Python/C++/Java/Typescript 等任何代码；
   - 绝不直接编写、执行或回答用户的答案；
   - 绝不输出 JSON 之外的任何解释/前缀/后缀文本；
   - 即使是“写代码/创建文件/写界面”这类任务，也只在 subtasks 的 role_prompt 里描述“去做什么”，代码由子智能体执行时去写。

输出格式示例（复杂任务，第二个子任务依赖第一个的产出）：
{{"subtasks": [{{"order": 1, "title": "子任务标题", "role_prompt": "你是……请……", "expect_output": "期望得到……", "required_tools": ["fs_read"], "depends_on": []}}, {{"order": 2, "title": "依赖上一步的子任务", "role_prompt": "你是……请……", "expect_output": "期望得到……", "required_tools": [], "depends_on": [1]}}]}}
简单任务只输出：
{{"subtasks": []}}

可用工具列表（子任务需要调用工具时，从以下工具中选择并在 required_tools 中填写工具名）：
{available_tools}
"""

# 编排器直接回答系统提示词模板（无子任务退化时使用，避免复用规划提示词；
# 保留占位符以注入 <预设提示>/<长期记忆>/<用户画像>/<情景记忆>/<行为规则>）
ORCHESTRATOR_DIRECT_ANSWER_SYSTEM_PROMPT_TEMPLATE = """你是一个智能助手，请直接回答用户的问题。

<预设提示>
{preset_prompt}
</预设提示>

{long_term_memory_block}
{user_profile_block}
{episodic_memory_block}
{procedural_instructions_block}
"""

# 编排器汇总提示词模板
ORCHESTRATOR_SUMMARIZE_PROMPT_TEMPLATE = """你是任务汇总智能体。用户的任务被拆分为多个子任务并行执行，请综合以下子任务结果，输出一份完整、连贯的最终回答。

用户任务：
{query}

子任务结果：
{sub_results_text}

要求：
1、回答必须完整覆盖用户任务的所有要点；
2、子任务失败或缺失的部分如实说明，禁止编造；
3、输出语言与用户任务保持一致。
"""


def build_system_prompt(
        template: str,
        *,
        preset_prompt: str,
        long_term_memory: str = "",
        user_profile: str = "",
        episodic_memory: str = "",
        procedural_instructions: str = "",
        tool_description: str = "",
) -> str:
    """构建系统提示词：<长期记忆>/<用户画像>/<情景记忆>/<行为规则> 为空时整块省略"""
    long_term_memory_block = (
        f"\n<长期记忆>\n{long_term_memory}\n</长期记忆>\n"
        if long_term_memory else ""
    )
    user_profile_block = (
        f"\n<用户画像>\n{user_profile}\n</用户画像>\n"
        if user_profile else ""
    )
    episodic_memory_block = (
        f"\n<情景记忆>\n{episodic_memory}\n</情景记忆>\n"
        if episodic_memory else ""
    )
    procedural_instructions_block = (
        f"\n<行为规则>\n{procedural_instructions}\n</行为规则>\n"
        if procedural_instructions else ""
    )
    return template.format(
        preset_prompt=preset_prompt,
        long_term_memory_block=long_term_memory_block,
        user_profile_block=user_profile_block,
        episodic_memory_block=episodic_memory_block,
        procedural_instructions_block=procedural_instructions_block,
        tool_description=tool_description,
    )


class SubTaskSpec(BaseModel):
    """子任务定义

    字段设计为宽松类型（order/title/role_prompt/expect_output 可缺省、required_tools 兼容字符串），
    因为 LLM 函数调用输出不稳定：实测 deepseek-v4-flash 会偶发缺失 order、或把数组字段字符串化。
    宽松解析后在 OrchestratorAgent._plan_node 中做归一化（补 order、丢弃关键字段缺失项、字符串转列表）。
    """
    order: int | None = None  # 子任务序号（LLM 偶发缺失，_plan_node 按位置补全）
    title: str = ""  # 子任务标题
    role_prompt: str = ""  # 子智能体角色提示词（作为子Agent的preset_prompt）
    expect_output: str = ""  # 期望输出描述
    required_tools: list[str] | str = Field(default_factory=list, description="需要的工具名列表，可为空；兼容LLM字符串化输出")
    # 依赖的前置子任务 order 列表；空 = 无依赖可立即执行。
    # LLM 给的非法值（自依赖/不存在的 order/字符串化）在 _plan_node 归一化时剔除，成环则断环，
    # 调度器绝不因脏依赖而挂死。
    depends_on: list[int] | str = Field(default_factory=list, description="依赖的前置子任务 order 列表，可为空；兼容LLM字符串化输出")
    task_id: UUID | None = None  # execute 节点派发时赋值 uuid4()


class SubTaskResult(BaseModel):
    """子任务执行结果"""
    order: int
    title: str
    status: str = "normal"  # normal / error / stop / timeout
    answer: str = ""
    error: str = ""
    latency: float = 0.0
    # 该子任务的用量（供带护栏的编排引擎做预算熔断）；0 = 未统计（如断点结果缓存复用）
    total_token_count: int = 0
    total_price: float = 0.0
    resumed: bool = False  # 是否从断点恢复


class SubTaskPlanInputSpec(BaseModel):
    """plan 节点 LLM 结构化输出用的子任务定义（不含 task_id，task_id 由系统派发）"""
    order: int | None = None  # 子任务序号（LLM 偶发缺失，_plan_node 按位置补全）
    title: str = ""  # 子任务标题
    role_prompt: str = ""  # 子智能体角色提示词（作为子Agent的preset_prompt）
    expect_output: str = ""  # 期望输出描述
    required_tools: list[str] | str = Field(default_factory=list, description="需要的工具名列表，可为空；兼容LLM字符串化输出")
    depends_on: list[int] | str = Field(default_factory=list, description="依赖的前置子任务 order 列表，无依赖留空；兼容LLM字符串化输出")


class SubTaskPlanInput(BaseModel):
    """任务分解计划（plan 节点 LLM 结构化输出；task_id 由系统派发，不在 LLM schema 中）"""
    subtasks: list[SubTaskPlanInputSpec] = Field(default_factory=list, description="子任务列表；任务无需分解时返回空列表")


class SubTaskPlan(BaseModel):
    """任务分解计划（保留用于兼容/测试；生产 plan 节点使用 SubTaskPlanInput）"""
    subtasks: list[SubTaskSpec] = Field(default_factory=list, description="子任务列表；任务无需分解时返回空列表")


class AgentConfig(BaseModel):
    """智能体配置信息，涵盖：LLM大语言模型、预设prompt、关联插件、知识库、工作流、是否开启长期记忆等内容，后期可以随时扩展"""
    # 代表用户的唯一标识及调用来源，默认来源是WEB_APP
    user_id: UUID
    invoke_from: InvokeFrom = InvokeFrom.WEB_APP

    # 最大迭代次数
    max_iteration_count: int = 30

    # 智能体预设提示词
    system_prompt: str = AGENT_SYSTEM_PROMPT_TEMPLATE
    preset_prompt: str = ""  # 预设prompt，默认为空，该值由前端用户在编排的时候记录，并填充到system_prompt中
    # 智能体长期记忆是否开启
    enable_long_term_memory: bool = False  # 是否开启会话信息汇总/长期记忆

    # 智能体使用的工具列表
    tools: list[BaseTool] = Field(default_factory=list)

    # 本地工具运行时：True 时 LOCAL_TOOL_NAMES 内的工具不服务器执行，
    # 而是在 _tools_node 里发 LOCAL_TOOL_CALL 事件、等待插件本地执行结果。
    local_tool_runtime: bool = False

    # 审核配置
    review_config: dict = Field(default_factory=lambda: DEFAULT_APP_CONFIG["review_config"])

    # 编排器配置（仅 OrchestratorAgent 使用）：resume_mode / max_sub_tasks / max_parallel / sub_task_timeout
    orchestrator_config: dict = Field(default_factory=dict)


class AgentState(MessagesState):
    """智能体状态类"""
    task_id: UUID  # 该次装填对应的任务id，每次运行时会使用独立的任务id
    iteration_count: int  # 迭代次数，默认0
    history: list[AnyMessage]  # 短期记忆（历史记录）
    long_term_memory: str  # 长期记忆
    # 注：langgraph 1.2.11 map_input 会丢弃 schema 外的输入键，这两个键必须在此声明，
    # 否则 state.get("user_profile"/"episodic_memory") 恒为空，<用户画像>/<情景记忆> 静默失效
    user_profile: str = ""  # 用户画像（语义记忆，Task 12 注入）
    episodic_memory: str = ""  # 情景记忆（经历召回，Task 19 注入）
    procedural_instructions: str = ""  # 程序记忆（行为规则/人设，Task 21 注入）

    # 编排器相关（带默认值，防 langgraph map_input 丢弃）
    sub_tasks: list[SubTaskSpec] = Field(default_factory=list)  # 规划结果
    sub_results: list[SubTaskResult] = Field(default_factory=list)  # 执行结果
    final_answer: str = ""  # 汇总最终答案（_summarize_node 写入，confirm_result 节点判断歧义用）
    plan_id: UUID | None = None  # 计划代际标识（plan 节点每次产出新计划时生成；断点记录代际）
    plan_feedback: str = ""  # 重新规划反馈（确认点1 replan / 确认点2 重新生成的原因，plan 重拆融合）
    plan_attempts: int = 0  # 重拆轮数（配合 2 轮上限防无限重拆；>0 即新代际，execute 前清旧断点）
    regenerate: bool = False  # 确认点2 重新生成标记（confirm_result 回 plan 时置位）
    # 失败自动重规划：子任务 error/timeout 时由 execute 直接回 plan 重拆，不弹确认框
    # （弹框会 wait_for_plan_choice 阻塞最长 300s，那就不叫"自动"了）
    auto_replan: bool = False  # 置位时 plan 后跳过 confirm_plan，直接 execute
    replan_reason: str = ""  # execute 判定的失败原因摘要（日志与事件展示用）
    budget_exhausted: bool = False  # 带护栏的编排引擎预算熔断置位（熔断不触发重规划）
    conversation_id: UUID | None = None  # 断点键一部分（chat_runner 注入）
    app_id: UUID | None = None  # 断点归属（chat_runner 注入）
    message_id: UUID | None = None  # 断点归属（chat_runner 注入）
    query: str = ""  # 原始用户提问，断点有效性校验
    resume: bool = False  # 恢复模式标记（FunctionCallAgent 条件入口用）
    resume_trigger: bool = False  # 请求级显式恢复标记（manual 模式）
    resume_message_id: UUID | None = None  # 断点续跑时的原始消息 id（断点按 message_id 定位，chat_runner 注入）
    local_tool_timeout_streak: int = 0  # 本地工具连续超时计数（0=正常；达到 LOCAL_TOOL_TIMEOUT_STREAK_LIMIT 后熔断）


# 知识库检索工具名称
DATASET_RETRIEVAL_TOOL_NAME = "dataset_retrieval"

# Agent超过最大迭代次数时提示内容
MAX_ITERATION_RESPONSE = "当前Agent迭代次数已超过限制，请重试"

ASK_USER_TOOL_NAME = "ask_user"
ASK_USER_WAIT_TIMEOUT = 300
# 本地工具结果回传超时（秒）：插件在 SSE 上收到 local_tool_call 后执行并回传。
# 若事件在长连接/传输中丢失，wait_for_tool_result 会整段阻塞——这里用较短的超时，
# 让 Agent 尽快拿到"本地工具执行出错"并重试写，而不是让用户在 300s 里干等。
# ask_user 仍需 300s（等真实用户输入），故分开。
LOCAL_TOOL_WAIT_TIMEOUT = 60

# 本地工具连续超时熔断（按 task_id/run 独立计数）：达到上限后，本 run 内后续本地工具
# 调用快速失败（不再各等 60s、也不再让 LLM 无限 60s×N 重试），并把"失败原因 + 兜底输出"
# 指引注入给模型——避免执行器断流（插件未重启/工具窗未打开/SSE 断流/本地 I/O 卡死）时
# 每次对话白白烧掉 N×60s，最终还把超时错误当回答返回。
LOCAL_TOOL_TIMEOUT_STREAK_LIMIT = 3
# 计入熔断连续计数的"超时类"错误前缀（插件结果通道失联/未就绪/通道异常；插件看门狗回传的
# "本地工具执行超时（插件看门狗 …）"同样命中——用 startswith 匹配）。普通执行错误说明插件
# 在回传，视为"执行器存活"，不计入连续超时。
LOCAL_TOOL_TIMEOUT_ERROR_MARKERS = ("本地工具执行超时", "本地工具结果通道未就绪", "本地工具结果通道异常")


class AskUserArgs(BaseModel):
    """ask_user 工具参数：向用户提问并等待选择"""
    question: str = Field(description="向用户展示的问题")
    options: list[str] = Field(default_factory=list, description="可选项列表，供用户单选")
    allow_custom: bool = Field(default=True, description="是否允许用户输入自定义选项")


def create_ask_user_tool() -> StructuredTool:
    """ask_user 占位工具：仅用于让 LLM 在 bind_tools 时知道可调用。

    其 func 不会被真正执行——FunctionCallAgent._tools_node 会对
    ASK_USER_TOOL_NAME 走特殊分支（发布事件 + 阻塞等待用户选择）。
    """
    return StructuredTool.from_function(
        name=ASK_USER_TOOL_NAME,
        func=lambda **kwargs: "",
        description=(
            "当任务存在多个可行方案或需要用户决策时调用：向用户展示问题与选项，"
            "等待用户选择后再继续。例如设计权限方案时可让用户选择 RBAC/ABAC/混合。"
        ),
        args_schema=AskUserArgs,
    )


class ConfirmVerdict(BaseModel):
    """汇总歧义判断：LLM 结构化输出"""
    need_confirm: bool = False  # 汇总结果是否需要用户确认
    reason: str = ""            # 需要确认的原因（need_confirm=True 时展示给用户）


ORCHESTRATOR_CONFIRM_PROMPT_TEMPLATE = (
    "你是任务结果审核助手。下面给出了用户的问题和基于子任务执行结果的最终汇总答案。\n"
    "请判断这个汇总答案是否完整、明确、无歧义，是否足以让用户直接采用：\n"
    "1. 答案完整且无歧义，用户可以直接采纳 → need_confirm=false\n"
    "2. 答案存在不确定性、缺少关键信息、涉及多个可选方向需要用户决策 → need_confirm=true，并在 reason 中简述需要用户确认的点\n"
    "只输出 JSON：{{'need_confirm': bool, 'reason': str}}"
)
