#!/usr/bin/env python
"""
@Time    : 2026/1/21 0:01
@Author  : sunxiaojie
@File    : app_config_service.py
"""
import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.language_model import LanguageModelManager
from internal.core.language_model.entities.model_entity import ModelParameterType
from internal.core.language_model.providers.custom_api.models import CUSTOM_API_PROVIDER
from internal.core.request_context import get_request_context
from internal.core.tools.api_tools.entities import ToolEntity
from internal.core.tools.api_tools.providers import ApiProviderManager
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.tools.mcp_client import MCPClientManager
from internal.core.tools.tool_gateway import ToolGateway
from internal.core.workflow import Workflow as WorkflowTool
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.entity.app_entity import AppConfigType, DEFAULT_APP_CONFIG
from internal.entity.skill_entity import SkillInput
from internal.entity.workflow_entity import WorkflowStatus
from internal.lib.helper import datetime_to_timestamp, get_value_type
from internal.model import (
    ApiTool,
    App,
    AppConfig,
    AppConfigVersion,
    AppDatasetJoin,
    Dataset,
    Skill,
    Workflow,
)

from .base_service import BaseService
from .language_model_service import LanguageModelService


@dataclass
class AppConfigService(BaseService):
    """应用配置服务"""
    db: AsyncSession
    api_provider_manager: ApiProviderManager
    builtin_provider_manager: BuiltinProviderManager
    language_model_manager: LanguageModelManager
    language_model_service: LanguageModelService

    async def _query_draft_app_config(self, app: App) -> AppConfigVersion:
        """查询应用的草稿配置；缺失时创建默认草稿并提交（独立事务边界）"""
        stmt = (
            select(AppConfigVersion)
            .where(
                AppConfigVersion.app_id == app.id,
                AppConfigVersion.config_type == AppConfigType.DRAFT,
            )
        )
        draft_app_config = await self.db.scalar(stmt)
        if not draft_app_config:
            draft_app_config = AppConfigVersion(
                app_id=app.id,
                version=0,
                config_type=AppConfigType.DRAFT,
                **DEFAULT_APP_CONFIG,
            )
            self.db.add(draft_app_config)
            await self.db.commit()  # 独立事务边界
        return draft_app_config

    async def get_draft_app_config(self, app: App) -> dict[str, Any]:
        """根据传递的应用获取该应用的草稿配置"""
        # 1、提取应用的草稿配置
        draft_app_config = await self._query_draft_app_config(app)

        # 2、校验model_config信息，如果使用了不存在的提供者或者模型，则使用默认值（宽松校验）
        validate_model_config = self._process_and_validate_model_config(dict(draft_app_config.model_config))
        if draft_app_config.model_config != validate_model_config:
            await self.update(draft_app_config, model_config=validate_model_config)

        # 3、循环遍历工具列表删除已经被删除的工具信息
        tools, validate_tools = await self._process_and_validate_tools(list(draft_app_config.tools))

        # 4、判断是否需要更新草稿配置中的工具列表信息
        if draft_app_config.tools != validate_tools:
            # 5、更新草稿配置中的工具列表
            await self.update(draft_app_config, tools=validate_tools)

        # 6、计算存在的知识库id列表，保持原始顺序，使用列表循环方式判断
        datasets, validate_datasets = await self._process_and_validate_datasets(list(draft_app_config.datasets))

        # 7、判断是否存在已删除知识库，如果存在就更新
        if set(validate_datasets) != set(draft_app_config.datasets):
            await self.update(draft_app_config, datasets=validate_datasets)

        # 8、校验工作流列表数据
        workflows, validate_workflows = await self._process_and_validate_workflows(list(draft_app_config.workflows))
        if set(validate_workflows) != set(draft_app_config.workflows):
            await self.update(draft_app_config, workflows=validate_workflows)

        # 9、校验skills信息
        skills, validate_skills = await self._process_and_validate_skills(list(draft_app_config.skills))
        if set(validate_skills) != set(draft_app_config.skills):
            await self.update(draft_app_config, skills=validate_skills)

        # 10、返回数据
        # updated_at 为 server_onupdate 列，update() 提交后 ORM 标记其过期；async 下惰性
        # SELECT 抛 MissingGreenlet——显式 refresh 读取 DB 最新值。
        await self.db.refresh(draft_app_config)
        return self._process_and_transformer_app_config(
            validate_model_config,
            tools,
            skills,
            workflows,
            datasets,
            draft_app_config,
        )

    async def get_app_config(self, app: App) -> dict[str, Any]:
        """根据传递的应用获取该应用的运行配置"""
        # 1、提取应用的配置（按 app_config_id 查库，无创建）
        app_config = await self.db.get(AppConfig, app.app_config_id) if app.app_config_id else None

        # 2、校验model_config信息，如果运行时配置里的model_config发生变化则进行更新
        validate_model_config = self._process_and_validate_model_config(dict(app_config.model_config))
        if app_config.model_config != validate_model_config:
            await self.update(app_config, model_config=validate_model_config)

        # 3、循环遍历工具列表删除已经被删除的工具信息
        tools, validate_tools = await self._process_and_validate_tools(list(app_config.tools))

        # 4、判断是否需要更新草稿配置中的工具列表信息
        if app_config.tools != validate_tools:
            # 5、更新草稿配置中的工具列表
            await self.update(app_config, tools=validate_tools)

        # 6、校验知识库列表，如果引用了不存在/被副除的知识库，需要剔除数据并更新，同时获取知识库的额外信息
        app_dataset_joins = await self._query_app_dataset_joins(app_config)
        origin_datasets = [app_dataset_join.dataset_id for app_dataset_join in app_dataset_joins]

        # 7、计算存在的知识库id列表，保持原始顺序，使用列表循环方式判断
        datasets, validate_datasets = await self._process_and_validate_datasets(origin_datasets)

        # 8、判断是否存在已删除知识库，如果存在就更新（独立事务边界）
        for dataset_id in (set(origin_datasets) - set(validate_datasets)):
            stmt = delete(AppDatasetJoin).where(
                AppDatasetJoin.dataset_id == dataset_id
            )
            await self.db.execute(stmt)
            await self.db.commit()  # 独立事务边界

        # 9、校验工作流列表数据
        workflows, validate_workflows = await self._process_and_validate_workflows(list(app_config.workflows))
        if set(validate_workflows) != set(app_config.workflows):
            await self.update(app_config, workflows=validate_workflows)

        # 10、校验skills信息
        skills, validate_skills = await self._process_and_validate_skills(list(app_config.skills))
        if set(validate_skills) != set(app_config.skills):
            await self.update(app_config, skills=validate_skills)
        # 10、返回数据（同 get_draft_app_config：server_onupdate 列 refresh 防 MissingGreenlet）
        await self.db.refresh(app_config)
        return self._process_and_transformer_app_config(
            validate_model_config,
            tools,
            skills,
            workflows,
            datasets,
            app_config,
        )

    async def _query_app_dataset_joins(self, app_config: AppConfig) -> list[AppDatasetJoin]:
        """按 app_id 查询应用的知识库关联记录"""
        stmt = select(AppDatasetJoin).where(AppDatasetJoin.app_id == app_config.app_id)
        return list((await self.db.scalars(stmt)).all())

    async def get_langchain_tools_by_tools_config(
            self,
            tools_config: list[dict],
            *,
            account_id: UUID | None = None,
    ) -> list[BaseTool]:
        """根据传递的工具配置列表获取langchain工具列表

        API 工具按 account_id 二次校验归属，防止跨租户引用他人工具。
        """
        tools = []
        for tool in tools_config:
            if tool["type"] == "builtin_tool":
                builtin = self.builtin_provider_manager.get_tool(
                    tool["provider"]["id"], tool["tool"]["name"]
                )
                if builtin:
                    # tools.append(builtin(**tool["tool"]["params"]))
                    tools.append(builtin)
            else:
                if account_id is not None:
                    stmt = select(ApiTool).where(
                        ApiTool.id == tool["tool"]["id"],
                        ApiTool.account_id == account_id,
                    )
                    api_tool = (await self.db.scalars(stmt)).first()
                else:
                    api_tool = await self.get(ApiTool, tool["tool"]["id"])
                if api_tool:
                    tools.append(
                        self.api_provider_manager.get_tool(
                            ToolEntity(
                                id=str(api_tool.id),
                                name=api_tool.name,
                                url=api_tool.url,
                                method=api_tool.method,
                                description=api_tool.description,
                                headers=api_tool.provider.headers,
                                parameters=api_tool.parameters,
                            )
                        )
                    )

        tools.extend(await MCPClientManager.discover_tools(account_id=account_id))
        return tools

    async def get_langchain_tools_by_workflow_ids(
            self,
            workflow_ids: list[UUID],
            *,
            account_id: UUID | None = None,
    ) -> list[BaseTool]:
        """根据传递的工作流配置列表获取langchain工具列表

        按 account_id 二次校验工作流归属，防止跨租户引用他人工作流。
        """
        # 1、根据传递的工作流id查询工作流记录信息
        stmt = (
            select(Workflow)
            .where(
                Workflow.id.in_(workflow_ids),
                Workflow.status == WorkflowStatus.PUBLISHED,
            )
        )
        if account_id is not None:
            stmt = stmt.where(Workflow.account_id == account_id)
        workflow_records = (await self.db.scalars(stmt)).all()

        # 2、循环遍历所有工作流记录列表
        workflows = []
        for workflow_record in workflow_records:
            try:
                # 3、创建工作流工具
                workflow_tool = WorkflowTool(workflow_config=WorkflowConfig(
                    account_id=workflow_record.account_id,
                    name=f"wf_{workflow_record.tool_call_name}",
                    description=workflow_record.description,
                    nodes=workflow_record.graph.get("nodes", []),
                    edges=workflow_record.graph.get("edges", []),
                ))
                workflows.append(workflow_tool)
            except Exception:
                continue

        return workflows

    async def get_langchain_tools_by_skill_ids(
            self,
            skill_ids: list[str],
            *,
            account_id: UUID | None = None,
    ) -> list[BaseTool]:
        """根据传递的skills_id列表获取langchain工具列表

        按 account_id 二次校验技能归属，防止跨租户引用他人技能。
        """
        stmt = select(Skill).where(Skill.id.in_(skill_ids))
        if account_id is not None:
            stmt = stmt.where(Skill.account_id == account_id)
        skill_records = (await self.db.scalars(stmt)).all()
        skills = []
        for skill_record in skill_records:
            try:
                skill_tool = await self._create_langchain_tool_from_skill(skill_record)
                skills.append(skill_tool)
            except Exception:
                continue
        return skills

    async def _create_langchain_tool_from_skill(
            self,
            skill_record: Skill,
    ) -> BaseTool:
        from internal.service.skill_service import SkillService

        skill_name = skill_record.name
        skill_description = skill_record.description or ""
        # 入口 SKILL.md 正文已入库，直接从 DB 读取（预览与构建工具同源）
        skill_content = skill_record.content or ""
        # 本地缓存目录（上传时解压到 storage/skills/{skill_id}/），运行期读取脚本
        cache_dir = SkillService._cache_dir(skill_record.id)

        # 收集技能包内所有子技能（排除入口本身）：路径 -> 名称/描述
        sub_skills = self._collect_sub_skills(cache_dir, skill_record.content)

        # 合成工具描述：入口描述 + 子技能能力清单，让模型判断何时调用该技能
        if sub_skills:
            capability_lines = [
                f"- {name}: {desc}" if desc else f"- {name}"
                for name, desc, _ in sub_skills
            ]
            tool_description = (
                f"{skill_description}\n\n"
                f"该技能包包含以下子技能（当任务匹配任意子技能能力时，必须调用本工具）：\n"
                + "\n".join(capability_lines)
            )
        else:
            tool_description = skill_description

        # 技能脚本只在独立子进程中执行，禁止在主 API 进程 import 用户上传代码。
        script_path = None
        tools_dir = cache_dir / "tools"
        if tools_dir.exists():
            for py_file in sorted(tools_dir.glob("*.py")):
                try:
                    tree = ast.parse(py_file.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, SyntaxError):
                    continue
                if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run" for node in tree.body):
                    script_path = py_file
                    break

        # load_language_model 为 async 方法，需 await 获取模型实例
        llm = await self.language_model_service.load_language_model({})

        tool_call_name = re.sub(r"[^a-zA-Z0-9_]", "_", str(skill_name))

        def skill_tool_func(query: str) -> str:
            if script_path is not None:
                if os.getenv("SKILL_EXECUTABLE_ENABLED", "false").lower() != "true":
                    return "可执行技能未启用：管理员需显式设置 SKILL_EXECUTABLE_ENABLED=true"
                return ToolGateway.skill(
                    script_path,
                    query,
                    timeout=int(os.getenv("SKILL_TOOL_TIMEOUT", "60")),
                )

            if not skill_content:
                return f"skills {skill_name} 没有可用的文档内容"

            # 1、构建技能包上下文：入口正文 + 子技能索引
            context = skill_content
            if sub_skills:
                index_lines = [
                    f"- {name}: {desc}" if desc else f"- {name}"
                    for name, desc, _ in sub_skills
                ]
                context += (
                    "\n\n## 本技能包包含以下子技能（按需使用）\n" + "\n".join(index_lines)
                )

            # 2、按 query 关键词命中子技能时，注入该子技能全文（让模型全面掌握被点名技能）
            query_lower = query.lower()
            for name, _, full_content in sub_skills:
                if name.lower() in query_lower and full_content:
                    context += (
                        f"\n\n## 子技能「{name}」完整内容\n{full_content}"
                    )
                    break

            from langchain_core.messages import HumanMessage, SystemMessage
            messages = [
                SystemMessage(content=context),
                HumanMessage(content=query),
            ]
            response = llm.invoke(messages)
            return response.content if hasattr(response, "content") else str(response)

        # 用StructuredTool显式指定 name和description
        from langchain_core.tools import StructuredTool

        skill_tool = StructuredTool.from_function(
            func=skill_tool_func,
            name=tool_call_name,
            description=tool_description,
            args_schema=SkillInput,
        )

        return skill_tool

    @staticmethod
    def _collect_sub_skills(cache_dir: Path, entry_content: str | None = None) -> list[tuple[str, str, str]]:
        """收集技能包内所有 SKILL.md 的名称/描述/全文（排除入口正文本身）

        返回 [(名称, 描述, 全文), ...]，按路径排序稳定。
        """
        if not cache_dir.exists():
            return []

        from internal.entity.skill_entity import FRONTMATTER_RE

        sub_skills = []
        for md_path in sorted(cache_dir.rglob("SKILL.md")):
            try:
                content = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # 跳过入口 SKILL.md：内容与入口正文一致（比较首行 frontmatter 分隔符特征）
            if entry_content and content.strip() == entry_content.strip():
                continue
            match = FRONTMATTER_RE.match(content)
            if not match:
                continue
            meta = {}
            for line in match.group("fm").splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
            name = meta.get("name", "").strip() or md_path.parent.name
            description = meta.get("description", "").strip()
            sub_skills.append((name, description, content))
        return sub_skills

    @classmethod
    def _process_and_transformer_app_config(
            cls,
            model_config: dict[str, Any],
            tools: list[dict],
            skills: list[dict],
            workflows: list[dict],
            datasets: list[dict],
            app_config: AppConfig | AppConfigVersion
    ) -> dict[str, Any]:
        """根据传递的插件列表、工作流列表、知识库列表以及应用配置创建字典信息"""
        return {
            "id": str(app_config.id),
            "model_config": model_config,
            "dialog_round": app_config.dialog_round,
            "preset_prompt": app_config.preset_prompt,
            "tools": tools,
            "skills": skills,
            "workflows": workflows,
            "datasets": datasets,
            "retrieval_config": app_config.retrieval_config,
            "long_term_memory": app_config.long_term_memory,
            "opening_statement": app_config.opening_statement,
            "opening_questions": app_config.opening_questions,
            "speech_to_text": app_config.speech_to_text,
            "text_to_speech": app_config.text_to_speech,
            "suggested_after_answer": app_config.suggested_after_answer,
            "review_config": app_config.review_config,
            "orchestrator_config": app_config.orchestrator_config,
            "updated_at": datetime_to_timestamp(app_config.updated_at),
            "created_at": datetime_to_timestamp(app_config.created_at)
        }

    async def _process_and_validate_tools(self, origin_tools: list[dict]) -> tuple[list[dict], list[dict]]:
        """根据传递的原始工具信息进行处理和校验"""
        # 使用 get_request_context() 获取请求上下文（ContextVar）
        ctx = get_request_context()
        # 1、循环遍历工具列表删除已经被删除的工具信息
        validate_tools = []
        tools = []
        for tool in origin_tools:
            if tool["type"] == "builtin_tool":
                # 2、查询内置工具提供者，并检测是否存在
                provider = self.builtin_provider_manager.get_provider(str(tool["provider_id"]))
                if provider is None:
                    continue
                # 3、获取提供者下的工具实体，并检测是否存在
                tool_entity = provider.get_tool_entity(str(tool["tool_id"]))
                if not tool_entity:
                    continue
                # 4、判断工具的params和草稿中的params是否一致，如果不一致则全部重置为默认值（或者考虑删除这个工具的引l用）
                param_keys = {param.name for param in tool_entity.params}
                if set(tool["params"].keys()) - param_keys:
                    tool["params"] = {}
                # 5、检验数据完毕，添加到validate_tools
                validate_tools.append(tool)
                # 6、组装内置工具展示信息
                provider_entity = provider.provider_entity
                tools.append({
                    "type": "builtin_tool",
                    "provider": {
                        "id": provider_entity.name,
                        "name": provider_entity.name,
                        "label": provider_entity.label,
                        "icon": f"{ctx.scheme}://{ctx.host}/builtin_tools/{provider_entity.name}/icon",
                        "description": provider_entity.description,
                    },
                    "tool": {
                        "id": tool_entity.name,
                        "name": tool_entity.name,
                        "label": tool_entity.label,
                        "description": tool_entity.description,
                        "params": tool["params"],
                    }
                })

            elif tool["type"] == "api_tool":
                # 7.查询数据库获取对应的工具记录，并检测是否存在
                stmt = select(ApiTool).where(
                    ApiTool.provider_id == tool["provider_id"],  # 如果是字典，使用方括号
                    ApiTool.name == tool["tool_id"]  # 如果是字典，使用方括号
                )

                tool_record = (await self.db.execute(stmt)).scalar_one_or_none()
                if not tool_record:
                    continue

                validate_tools.append(tool)

                # 8、数据检验成功，添加validate_tools
                provider = tool_record.provider
                tools.append({
                    "type": "api_tool",
                    "provider": {
                        "id": str(provider.id),
                        "name": provider.name,
                        "label": provider.name,
                        "icon": provider.icon,
                        "description": provider.description,
                    },
                    "tool": {
                        "id": str(tool_record.id),
                        "name": tool_record.name,
                        "label": tool_record.name,
                        "description": tool_record.description,
                        "params": {},
                    }
                })

        return tools, validate_tools

    async def _process_and_validate_datasets(self, origin_datasets: list[dict]) -> tuple[list[dict], list[dict]]:
        """根据传递的知识库井返回知识库配置与校验后的数据"""
        # 1、校验知识库配置列表，如果引用了不存在的/被删除的知识库，则需要剔除数据并更新，同时获取知识库的额外信息
        datasets = []

        if origin_datasets:
            stmt = select(Dataset).where(Dataset.id.in_(origin_datasets))
            dataset_records = (await self.db.execute(stmt)).scalars().all()
        else:
            dataset_records = []

        dataset_dict = {str(dataset_record.id): dataset_record for dataset_record in dataset_records}
        dataset_sets = set(dataset_dict.keys())

        # 2、计算存在的知识库id列表，保持原始顺序，使用列表循环方式判断
        # 注意：origin_datasets 可能是 UUID 对象（来自 app_dataset_join）或字符串（来自草稿 JSONB），
        # 统一转 str 再与 dataset_sets（str 集合）比较，避免类型不匹配导致误判为"已删除"而删掉关联
        validate_datasets = [
            dataset_id for dataset_id in origin_datasets
            if str(dataset_id) in dataset_sets
        ]

        # 3、循环获取知识库数据
        for dataset_id in validate_datasets:
            dataset = dataset_dict.get(str(dataset_id))
            datasets.append({
                "id": str(dataset.id),
                "name": dataset.name,
                "icon": dataset.icon,
                "description": dataset.description,
            })

        return datasets, validate_datasets

    def _process_and_validate_model_config(self, origin_model_config: dict[str, Any]) -> dict[str, Any]:
        """根据传递的模型配置处理并校验，随后返回校验后的信息（纯内存计算，保持同步）"""

        # 1、判断model_config是否为字典，如果不是则直接返回默认值
        if not isinstance(origin_model_config, dict):
            return DEFAULT_APP_CONFIG["model_config"]

        # 2、提取origin_model_config中provider、model、parameters对应的信息
        model_config = {
            "provider": origin_model_config.get("provider", ""),
            "model": origin_model_config.get("model", ""),
            "parameters": origin_model_config.get("parameters", {}),
        }

        # 3、判断provider是否存在、类型是否正确，如果不符合规则则返回默认值
        if not model_config["provider"] or not isinstance(model_config["provider"], str):
            return DEFAULT_APP_CONFIG["model_config"]

        # 4、判断model是否存在，类型是否正确，如果不符合则返回默认值
        if not model_config["model"] or not isinstance(model_config["model"], str):
            return DEFAULT_APP_CONFIG["model_config"]

        # 4.1 custom_api 是按账号懒合并的虚拟 provider：此处同步校验路径可能尚未合并，
        #     不能调会抛 NotFound 的 get_provider/get_model_entity（否则 500）。
        #     对 model key 做轻量校验即放行（用户自有的自定义模型，载入期由 load_language_model 强校验）。
        if model_config["provider"] == CUSTOM_API_PROVIDER:
            if not model_config["model"].startswith(f"{CUSTOM_API_PROVIDER}/"):
                return DEFAULT_APP_CONFIG["model_config"]
            if not isinstance(model_config["parameters"], dict):
                model_config["parameters"] = {}
            return model_config

        # 5、判断provider是否存在、类型是否正确，如果不符合规则则返回默认值
        provider = self.language_model_manager.get_provider(model_config["provider"])
        if provider is None:
            return DEFAULT_APP_CONFIG["model_config"]

        model_entity = provider.get_model_entity(model_config["model"])
        if model_entity is None:
            return DEFAULT_APP_CONFIG["model_config"]

        # 6、判断parameters信息类型是否错误，如果错误则设置为默认值
        if not isinstance(model_config["parameters"], dict):
            model_config["parameters"] = {
                parameter.name: parameter.default for parameter in model_entity.parameters
            }

        # 6、剔除传递的多余的parameter，亦或者是少传递的参数使用默认值补上
        parameters = {}
        for parameter in model_entity.parameters:
            # 7、从model_config中获取参数值，如果不存在则设置为默认值
            parameter_value = model_config["parameters"].get(parameter.name, parameter.default)

            # 8、判断参数是否必填
            if parameter.required:
                # 9、参数必填，则值不允许为None，如果为None则设置默认值
                if parameter_value is None:
                    parameter_value = parameter.default
                else:
                    # 10、值非空则校验数据类型是否正确，不正确则设置默认值
                    if get_value_type(parameter_value) != parameter.type.value:
                        parameter_value = parameter.default
            else:
                # 11、参数非必填，数据非空的情况下需要校验
                if (
                        parameter_value is not None
                        and get_value_type(parameter_value) != parameter.type.value
                ):
                    parameter_value = parameter.default

            # 12、判断参数是否存在options，如果存在则数值必须在options中选择
            if parameter.options and parameter_value not in parameter.options:
                parameter_value = parameter.default

            # 13、参数类型为int/float，如果存在min/max时候需要校验
            if (
                    parameter.type in [ModelParameterType.INT, ModelParameterType.FLOAT]
                    and parameter_value is not None
                    # 14、校验数值的min/max
                    and (
                        (parameter.min is not None and parameter_value < parameter.min)
                        or (parameter.max is not None and parameter_value > parameter.max)
                    )
            ):
                parameter_value = parameter.default

            parameters[parameter.name] = parameter_value

        model_config["parameters"] = parameters

        return model_config

    async def _process_and_validate_workflows(self, origin_workflows: list[UUID]) -> tuple[list[dict], list[UUID]]:
        """根据传递的工作流列表并返回工作流配置和校验后的数据"""
        # 1、校验工作流配置列表，如果引用了不存在/被删除的工作流，则需要提出数据并更新，同时获取工作流的额外信息
        workflows = []
        stmt = select(Workflow).where(
            Workflow.id.in_(origin_workflows),
            Workflow.status == WorkflowStatus.PUBLISHED,
        )
        workflow_records = (await self.db.scalars(stmt)).all()
        workflow_dict = {str(workflow_record.id): workflow_record for workflow_record in workflow_records}
        workflow_sets = set(workflow_dict.keys())

        # 2、计算存在的工作流id列表，为了保留原始顺序，使用列表循环的方式来判断
        validate_workflows = [workflow_id for workflow_id in origin_workflows if workflow_id in workflow_sets]

        # 3、循环获取工作流数据
        for workflow_id in validate_workflows:
            workflow = workflow_dict.get(str(workflow_id))
            workflows.append({
                "id": str(workflow.id),
                "name": workflow.name,
                "icon": workflow.icon,
                "description": workflow.description,
            })

        return workflows, validate_workflows

    async def _process_and_validate_skills(self, origin_skills: list[UUID]) -> tuple[list[dict], list[UUID]]:
        """根据传递的技能列表并返回技能配置和校验后的数据"""
        # 1、校验技能列表，如果引用了不存在/被删除的技能，则需要剔除数据并更新，同时获取技能的额外信息
        skills = []
        stmt = select(Skill).where(
            Skill.id.in_(origin_skills),
        )
        skill_records = (await self.db.scalars(stmt)).all()
        skill_dict = {str(skill_record.id): skill_record for skill_record in skill_records}
        skill_sets = set(skill_dict.keys())

        # 2、计算存在的技能id列表，为了保留原始顺序，使用列表循环的方式来判断
        validate_skills = [skill_id for skill_id in origin_skills if str(skill_id) in skill_sets]

        # 3、循环获取技能数据
        for skill_id in validate_skills:
            skill = skill_dict.get(str(skill_id))
            skills.append({
                "id": str(skill.id),
                "name": skill.name,
                "icon": skill.icon or "",
                "description": skill.description or "",
            })

        return skills, validate_skills
