#!/usr/bin/env python
"""
@Time    : 2026/1/26 0:06
@Author  : sunxiaojie
@File    : workflow_service.py
"""
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.core.request_context import get_request_context
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from internal.core.workflow import Workflow as WorkflowTool
from internal.core.workflow.entities.edge_entity import BaseEdgeData
from internal.core.workflow.entities.node_entity import BaseNodeData, NodeStatus, NodeType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.nodes import (
    CodeNodeData,
    DatasetRetrievalNodeData,
    EndNodeData,
    HttpRequestNodeData,
    LLMNodeData,
    StartNodeData,
    TemplateTransformNodeData,
    ToolNodeData,
)
from internal.core.workflow.utils.subgraph import build_subgraph_config, cleanup_stale_refs
from internal.entity.workflow_entity import (
    DEFAULT_WORKFLOW_CONFIG,
    WorkflowResultStatus,
    WorkflowStatus,
)
from internal.exception import (
    FailedException,
    ForbiddenException,
    NotFoundException,
    ValidateException,
    extract_exception_message,
)
from internal.model import Account, ApiTool, Dataset, Workflow, WorkflowResult
from internal.schema.workflow_schema import CreateWorkflowReq, GetWorkflowsWithPageReq
from internal.service import BaseService
from package.paginator import Paginator

logger = logging.getLogger(__name__)


def build_error_stream(error_message: str) -> AsyncGenerator:
    """构建单条error事件的流式生成器。

    注意：不能把异常对象/变量延迟到生成器体内引用（except块结束后异常变量会被Python清除，
    生成器延迟执行时会触发 NameError），所以这里只接收已经提取好的错误字符串。
    """
    error_data = {
        "id": str(uuid.uuid4()),
        "error": error_message,
        "error_node_id": None,
        "error_node_title": None,
    }
    yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"


@dataclass
class WorkflowService(BaseService):
    """工作流服务"""
    db: AsyncSession
    builtin_provider_manager: BuiltinProviderManager

    async def create_workflow(self, req: CreateWorkflowReq, account: Account) -> Workflow:
        """根据传递的请求信息创建工作流"""
        # 1、根据传递的工作流工具名称查询工作流信息
        stmt = (
            select(Workflow)
            .where(
                Workflow.tool_call_name == req.tool_call_name.strip(),
                Workflow.account_id == account.id,
            )
        )
        check_workflow = (await self.db.execute(stmt)).scalar_one_or_none()
        if check_workflow:
            raise ValidateException(f"在当前账号下已创建[{req.tool_call_name}]工作流，不支持重名")

        # 2、调用数据库服务创建工作流
        return await self.create(Workflow, **{
            **req.model_dump(),
            **DEFAULT_WORKFLOW_CONFIG,
            "account_id": account.id,
            "is_debug_passed": False,
            "status": WorkflowStatus.DRAFT,
            "tool_call_name": req.tool_call_name.strip(),
        })

    async def get_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """根据传递的工作流id，获取指定的工作流基础信息"""
        # 1、查询数据库获取工作流基础信息
        workflow = await self.get(Workflow, workflow_id)

        # 2、判断工作流是否存在
        if workflow is None:
            raise NotFoundException("该工作流不存在，请核实后重试")

        # 3、判断当前账号是否有权限访问该应用
        if workflow.account_id != account.id:
            raise ForbiddenException("当前账号无权限访问该应用，请核实后尝试")

        return workflow

    async def delete_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """根据传递的工作流id+账号信息，删除指定的工作流"""
        # 1、获取工作流基础信息并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、删除工作流
        await self.delete(workflow)

        return workflow

    async def update_workflow(self, workflow_id: UUID, account: Account, **kwargs) -> Workflow:
        """根据传递的工作流id+请求更新工作流基础信息"""
        # 1、获取工作流基础信息并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、根据传递的工具调用名字查询是否存在重名工作流
        stmt = select(Workflow).where(
            Workflow.tool_call_name == kwargs.get("tool_call_name", "").strip(),
            Workflow.account_id == account.id,
            Workflow.id != workflow.id,
        )
        check_workflow = (await self.db.scalars(stmt)).one_or_none()
        if check_workflow:
            raise ValidateException(f"在当前账号下已创建[{kwargs.get('tool_call_name', '')}]工作流，不支持重名")

        # 3、更新工作流基础信息
        await self.update(workflow, **kwargs)

        return workflow

    async def get_workflows_with_page(
            self, req: GetWorkflowsWithPageReq,
            account: Account
    ) -> tuple[list[Workflow], Paginator]:
        """根据传递的信息获取工作流分页列表数据"""
        # 1、构建分页器
        paginator = Paginator(db=self.db, req=req)

        # 2、构建筛选器
        filters = [Workflow.account_id == account.id]
        if req.search_word:
            filters.append(Workflow.name.ilike(f"%{req.search_word}%"))
        if req.status:
            filters.append(Workflow.status == req.status)

        # 3、分页查询数据
        stmt = select(Workflow).where(*filters).order_by(desc(Workflow.created_at))
        workflows = await paginator.paginate(stmt)

        return workflows, paginator

    async def update_draft_graph(self, workflow_id: UUID, draft_graph: dict[str, Any], account: Account) -> Workflow:
        """根据传递的工作流id+草稿图配置+账号更新工作流的草稿图"""
        # 1、根据传递的id获取工作流并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、校验传递的草稿图配置，因为有可能边有可能还未建立，所以需要校验关联的数据
        validate_draft_graph = await self._validate_graph(draft_graph, account)

        # 3、更新工作流草稿图配置，每次修改都将is_debug_passed的值重置为False，该处可以优化对比字典里除posit
        await self.update(workflow, draft_graph=validate_draft_graph, is_debug_passed=False)

        return workflow

    async def get_draft_graph(self, workflow_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的工作流id+账号信息，获取指定工作流的草稿配置信息"""
        # 请求上下文（scheme/host 来自 ContextVar）
        ctx = get_request_context()
        # 1、根据传递的id获取工作流并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、提取草稿图结构信息并校验(不更新校验后的数据到数据库)
        draft_graph = workflow.draft_graph
        validate_draft_graph = await self._validate_graph(draft_graph, account)

        # 3、循环遍历节点信息，为工具节点/知识库节点附加元数据
        for node in validate_draft_graph["nodes"]:
            if node.get("node_type") == NodeType.TOOL:
                # 4、判断工具的类型执行不同的操作
                if node.get("tool_type") == "builtin_tool":
                    # 5、节点类型为工具，则附加工具的名称、图标、参数等额外信息
                    provider = self.builtin_provider_manager.get_provider(node.get("provider_id"))
                    if provider is None:
                        continue

                    # 6、获取提供者下的工具实体，并检测是否存在
                    tool_entity = provider.get_tool_entity(node.get("tool_id"))
                    if not tool_entity:
                        continue

                    # 7、判断工具的params和草稿中的params是否一致，如果不一致则全部重置为默认值（或者考虑删除）
                    param_keys = {param.name for param in tool_entity.params}
                    params = node.get("params")
                    if set(params.keys()) - param_keys:
                        params = {
                            param.name: param.default
                            for param in tool_entity.params
                            if param.default is not None
                        }

                    # 8、数据校验成功附加展示信息
                    provider_entity = provider.provider_entity
                    node["meta"] = {
                        "type": "builtin_tool",
                        "provider": {
                            "id": provider_entity.name,
                            "name": provider_entity.name,
                            "label": provider_entity.label,
                            "icon": f"{ctx.scheme}://{ctx.host}/builtin_tools/{provider_entity.name}.icon",
                            "description": provider_entity.description,
                        },
                        "tool": {
                            "id": tool_entity.name,
                            "name": tool_entity.name,
                            "label": tool_entity.label,
                            "description": tool_entity.description,
                            "params": params,
                        }
                    }
                elif node.get("tool_type") == "api_tool":
                    # 9、查询数据库获取对应的工具记录，并检测是否存在
                    stmt = select(ApiTool).where(
                        ApiTool.provider_id == node.get("provider_id"),
                        ApiTool.name == node.get("tool_id"),
                        ApiTool.account_id == account.id,
                    )
                    tool_record = (await self.db.execute(stmt)).scalar_one_or_none()
                    if not tool_record:
                        continue

                    # 10、组装api工具展示信息
                    provider = tool_record.provider
                    node["meta"] = {
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
                    }
                else:
                    node["meta"] = {
                        "type": "api_tool",
                        "provider": {
                            "id": "",
                            "name": "",
                            "label": "",
                            "icon": "",
                            "description": "",
                        },
                        "tool": {
                            "id": "",
                            "name": "",
                            "label": "",
                            "description": "",
                            "params": {},
                        }
                    }
            elif node.get("node_type") == NodeType.DATASET_RETRIEVAL:
                # 5、节点类型为知识库检索，需要附加知识库的名称、图标等信息
                stmt = select(Dataset).where(
                    Dataset.id.in_(node.get("dataset_ids", [])),
                    Dataset.account_id == account.id,
                )
                datasets = (await self.db.execute(stmt)).scalars().all()
                node["meta"] = {
                    "datasets": [{
                        "id": dataset.id,
                        "name": dataset.name,
                        "icon": dataset.icon,
                        "description": dataset.description,
                    } for dataset in datasets]
                }

        return validate_draft_graph

    async def debug_workflow(
            self,
            workflow_id: UUID,
            inputs: dict[str, Any],
            account: Account,
            node_ids: list[UUID] | None = None,
    ) -> AsyncGenerator:
        """调试指定的工作流API接口，该接口为流式事件输出。node_ids非空时仅运行选中节点的上游闭包子图"""
        # 1、根据传递的id获取工作流并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、校验node_ids是否存在于草稿图
        if node_ids:
            draft_node_ids = {str(n.get("id")) for n in workflow.draft_graph.get("nodes", [])}
            invalid = [str(nid) for nid in node_ids if str(nid) not in draft_node_ids]
            if invalid:
                raise ValidateException(f"工作流中不存在节点: {', '.join(invalid)}，请核实后重试")

        # 3、构建工作流配置（node_ids时先构建上游闭包子图）
        workflow_config = WorkflowConfig(
            account_id=account.id,
            name=workflow.tool_call_name,
            description=workflow.description,
            nodes=workflow.draft_graph.get("nodes", []),
            edges=workflow.draft_graph.get("edges", []),
        )
        if node_ids:
            workflow_config = build_subgraph_config(
                workflow_config, [UUID(str(nid)) for nid in node_ids]
            )

        # 4、创建工作流工具（构造失败时返回单条error事件流，避免整请求500）
        try:
            workflow_tool = WorkflowTool(workflow_config=workflow_config)
        except Exception as e:
            async for item in build_error_stream(extract_exception_message(e)):
                yield item
            return

        # 5、定义变量存储所有节点运行结果与失败/跳过节点
        node_results = []
        failed_node_ids: list[str] = []
        skipped_node_ids: list[str] = []
        end_result = None

        # 6、添加数据库工作流运行结果记录
        workflow_result = await self.create(
            WorkflowResult, app_id=None, account_id=account.id, workflow_id=workflow.id,
            graph=workflow_config.model_dump(mode="json"), state=[], latency=0,
            status=WorkflowResultStatus.RUNNING,
        )

        # 7、调用stream服务获取工具信息
        start_at = time.perf_counter()
        try:
            for chunk in workflow_tool.stream(inputs):
                # 8、chunk的格式为:{"node_name": WorkflowState}，所以需要取出节点响应结构的第1个key
                first_key = next(iter(chunk))
                node_result = chunk[first_key]["node_results"][0]
                node_result_dict = node_result.model_dump(mode="json")
                node_results.append(node_result_dict)

                # 9、统计失败/跳过节点
                if node_result.status == NodeStatus.FAILED:
                    failed_node_ids.append(str(node_result.node_data.id))
                elif node_result.status == NodeStatus.SKIPPED:
                    skipped_node_ids.append(str(node_result.node_data.id))
                if node_result.node_data.node_type == NodeType.END:
                    end_result = node_result

                # 10、组装响应数据并流式事件输出（顶层带node_id供前端定位画布节点）
                data = {
                    "id": str(uuid.uuid4()),
                    "node_id": str(node_result.node_data.id),
                    **node_result_dict,
                }
                yield f"event: workflow\ndata: {json.dumps(data)}\n\n"

            # 11、汇总整体状态
            if end_result and end_result.status == NodeStatus.SUCCEEDED:
                overall_status = "partial_failed" if failed_node_ids else "succeeded"
            else:
                overall_status = "failed"

            # 12、发送summary事件
            summary = {
                "status": overall_status,
                "failed_node_ids": failed_node_ids,
                "skipped_node_ids": skipped_node_ids,
                "node_count": len(node_results),
                "latency": time.perf_counter() - start_at,
            }
            yield f"event: summary\ndata: {json.dumps(summary, ensure_ascii=False)}\n\n"

            # 13、更新运行结果记录
            await self.update(
                workflow_result,
                status=(
                    WorkflowResultStatus.SUCCEEDED
                    if overall_status != "failed"
                    else WorkflowResultStatus.FAILED
                ),
                state=node_results,
                latency=(time.perf_counter() - start_at),
            )

            # 14、仅整图调试且全部成功时置为调试通过
            if not node_ids and overall_status == "succeeded":
                await self.update(workflow, is_debug_passed=True)

            # 15、全局失败时额外发送error事件（取首个失败节点）
            if overall_status == "failed":
                error_node_id = failed_node_ids[0] if failed_node_ids else None
                error_node_title = None
                error_message = "工作流运行失败"
                if failed_node_ids:
                    failed_node = next(
                        (r for r in node_results if str(r.get("node_id", "")) == error_node_id),
                        None,
                    )
                    if failed_node:
                        error_node_title = failed_node.get("node_data", {}).get("title", "")
                        error_message = failed_node.get("error") or error_message
                error_data = {
                    "id": str(uuid.uuid4()),
                    "error": error_message,
                    "error_node_id": error_node_id,
                    "error_node_title": error_node_title,
                }
                yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 16、兜底：流式执行过程异常（非节点级），保证不中断连接
            error_data = {
                "id": str(uuid.uuid4()),
                "error": extract_exception_message(e),
                "error_node_id": None,
                "error_node_title": None,
            }
            yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            await self.update(
                workflow_result, status=WorkflowResultStatus.FAILED,
                state=node_results, latency=(time.perf_counter() - start_at),
            )

    async def publish_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """根据传递的工作流id，发布指定的工作流"""
        # 1、根据传递的id获取工作流并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、校验工作流是否调试通过
        if not workflow.is_debug_passed:
            raise FailedException("该工作流未调试通过，请调试通过后发布")

        # 3、使用WorkflowConfig二次校验，如果校验失败则不发布
        try:
            WorkflowConfig(
                account_id=account.id,
                name=workflow.tool_call_name,
                description=workflow.description,
                nodes=workflow.draft_graph.get("nodes", []),
                edges=workflow.draft_graph.get("edges", []),
            )
        except Exception:
            await self.update(workflow, is_debug_passed=False)
            raise ValidateException("工作流配置校验失败，请核实后重试")

        # 4、更新工作流的发布状态
        await self.update(workflow, graph=workflow.draft_graph, is_debug_passed=False, status=WorkflowStatus.PUBLISHED)
        return workflow

    async def cancel_publish_workflow(self, workflow_id: UUID, account: Account) -> Workflow:
        """取消发布指定的工作流"""
        # 1、根据传递的id获取工作流并校验权限
        workflow = await self.get_workflow(workflow_id, account)

        # 2、校验工作流是否为已发布的状态
        if workflow.status != WorkflowStatus.PUBLISHED:
            raise FailedException("该工作流未发布无法取消发布")

        # 3、更新发布状态并删除运行图草稿配置
        await self.update(workflow, graph={}, is_debug_passed=False, status=WorkflowStatus.DRAFT)

        return workflow

    async def _validate_graph(self, graph: dict[str, Any], account: Account) -> dict[str, Any]:
        """校验传递的graph信息，涵盖nodes和edges对应的数据，该函数使用相对宽松的校验方式"""
        # 1、提取nodes和edges数据
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # 2、构建节点类型与节点数据类映射
        node_data_classes = {
            NodeType.START: StartNodeData,
            NodeType.END: EndNodeData,
            NodeType.LLM: LLMNodeData,
            NodeType.TEMPLATE_TRANSFORM: TemplateTransformNodeData,
            NodeType.DATASET_RETRIEVAL: DatasetRetrievalNodeData,
            NodeType.CODE: CodeNodeData,
            NodeType.TOOL: ToolNodeData,
            NodeType.HTTP_REQUEST: HttpRequestNodeData,
        }

        # 3、循环校验nodes中各个节点对应的数据
        node_data_dict: dict[UUID, BaseNodeData] = {}
        start_nodes = 0
        end_nodes = 0
        for node in nodes:
            try:
                # 4、校验传递的node数据是不是字典，如果不是则跳过当前数据
                if not isinstance(node, dict):
                    raise ValidateException("工作流节点数据类型出错，请核实后重试")

                # 5、提取节点的node_type类型，并判断类型是否正确
                node_type = node.get("node_type", "")
                node_data_cls = node_data_classes.get(node_type, None)
                if node_data_cls is None:
                    raise ValidateException("工作流节点类型出错，请核实后重试")

                # 6、实例化节点数据类型，如果出错则跳过当前数据
                node_data = node_data_cls(**node)

                # 7、判断节点id是否唯一，如果不唯一，则将当前节点清除
                if node_data.id in node_data_dict:
                    raise ValidateException("工作流节点id必须唯一，请核实后重试")

                # 8、判断节点title是否唯一，如果不唯一，则将当前节点清除
                if any(item.title.strip() == node_data.title.strip() for item in node_data_dict.values()):
                    raise ValidateException("工作流节点title必须唯一，请核实后重试")

                # 9、对特殊节点进行判断，涵盖开始/结束/知识库检索/工具
                if node_data.node_type == NodeType.START:
                    if start_nodes >= 1:
                        raise ValidateException("工作流中只允许有1个开始节点")
                    start_nodes += 1
                elif node_data.node_type == NodeType.END:
                    if end_nodes >= 1:
                        raise ValidateException("工作流中只允许有1个结束节点")
                    end_nodes += 1
                elif node_data.node_type == NodeType.DATASET_RETRIEVAL:
                    # 10、剔除关联知识库列表中不属于当前账户的数据（校验全部知识库，不做数量截断）
                    stmt = (
                        select(Dataset)
                        .where(
                            Dataset.id.in_(node_data.dataset_ids),
                            Dataset.account_id == account.id,
                        )
                    )
                    datasets = (await self.db.scalars(stmt)).all()
                    node_data.dataset_ids = [dataset.id for dataset in datasets]

                # 13、将数据添加到node_data_dict中
                node_data_dict[node_data.id] = node_data
            except Exception as e:
                # 宽松校验：非法节点/边从草稿中剔除，但必须记录日志便于排查
                logger.warning("节点 %s 校验失败并已剔除: %s", node.get("title", "未知"), e)
                continue

        # 14、循环校验edges中各个节点对应的数据
        edge_data_dict: dict[UUID, BaseEdgeData] = {}
        for edge in edges:
            try:
                # 15、边类型为非字典则抛出错误，否则转换成BaseEdgeData
                if not isinstance(edge, dict):
                    raise ValidateException("工作流边数据类型出错，请核实后重试")
                edge_data = BaseEdgeData(**edge)

                # 16、校验边edges的id是否唯一
                if edge_data.id in edge_data_dict:
                    raise ValidateException("工作流边数据id必须唯一，请核实后重试")

                # 17、校验边中的source/target/source_type/target_type必须和nodes对得上
                if (
                        edge_data.source not in node_data_dict
                        or edge_data.source_type != node_data_dict[edge_data.source].node_type
                        or edge_data.target not in node_data_dict
                        or edge_data.target_type != node_data_dict[edge_data.target].node_type
                ):
                    raise ValidateException("工作流边起点/终点对应的节点不存在或类型错误，请核实后重试")

                # 18、校验边Edges里的边必须唯一(source+target必须唯一)
                if any(
                        (item.source == edge_data.source and item.target == edge_data.target)
                        for item in edge_data_dict.values()
                ):
                    raise ValidateException("工作流边数据不能重复添加")

                # 19、基础数据校验通过，将数据添加到edge_data_dict中
                edge_data_dict[edge_data.id] = edge_data
            except Exception:
                continue

        # 20、清理失效引用：删除节点后残留的引用（END出参/节点入参指向不存在的节点）自动移除
        cleanup_stale_refs(list(node_data_dict.values()))

        return {
            "nodes": [node_data.model_dump(mode="json") for node_data in node_data_dict.values()],
            "edges": [edge_data.model_dump(mode="json") for edge_data in edge_data_dict.values()],
        }
