#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/27 19:35
@Author : sunxiaojie
@File   : open_api_schema.py
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from internal.exception import ValidateException


class ParameterType(str, Enum):
    """参数支持的类型"""
    STR = "str"
    INT = "int"
    BOOL = "bool"
    FLOAT = "float"


ParameterTypeMap = {
    ParameterType.STR: str,
    ParameterType.INT: int,
    ParameterType.FLOAT: float,
    ParameterType.BOOL: bool
}


class ParameterIn(str, Enum):
    """参数支持存放的位置"""
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"
    REQUEST_BODY = "request_body"


class OpenApiSchema(BaseModel):
    """OpenAPI规范数据结构"""
    server: str = Field(default="", validate_default=True, description="工具提供商的服务基础地址")
    description: str = Field(default="", validate_default=True, description="工具提供商的描述信息")
    paths: dict[str, dict] = Field(default=dict, validate_default=True, description="工具提供商的路径参数字典")

    @field_validator("server", mode="before")
    @classmethod
    def validate_server(cls, server: str) -> str:
        """校验server数据"""
        if server is None or server == "":
            raise ValidateException("server不能为空且为字符串")
        return server

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, description: str) -> str:
        """校验description数据"""
        if description is None or description == "":
            raise ValidateException("description不能为空且为字符串")
        return description

    @field_validator("paths", mode="before")
    @classmethod
    def validate_paths(cls, paths: dict[str, dict]) -> dict[str, dict]:
        """校验paths数据"""
        # 1、paths不能为空且类型为字典
        if not paths or not isinstance(paths, dict):
            raise ValidateException("openapi_schema中的paths不能为空且必须为字典")
        # 2、提取paths里的每一个元素，并获取元素下的get/post方法对应的值
        methods = ["get", "post"]
        interfaces = []
        extra_paths = {}
        for path, path_item in paths.items():
            for method in methods:
                # 3、检测是否存在特定的方法并提取信息
                if method in path_item:
                    interfaces.append({
                        "path": path,
                        "method": method,
                        "operation": path_item[method],
                    })
        # 4、遍历提取到的所有接口并校验信息，涵盖operationId唯一标识，parameters参数
        operation_ids = []
        for interface in interfaces:
            # 5、校验description、operationId、parameters字段
            if not isinstance(interface["operation"].get("description"), str):
                raise ValidateException("description不能为空且为字符串")
            if not isinstance(interface["operation"].get("operationId"), str):
                raise ValidateException("operationId不能为空且为字符串")
            if not isinstance(interface["operation"].get("parameters"), list):
                raise ValidateException("parameters必须是列表或者为空")
            # 6、检测operationId是否是唯一的
            if interface["operation"]["operationId"] in operation_ids:
                raise ValidateException(f"operationId必须唯一，{interface['operation']['operationId']}出现重复")
            operation_ids.append(interface["operation"]["operationId"])
            # 7、校验parameters参数格式是否正确
            for parameter in interface["operation"].get("parameters", []):
                # 8、检验name/in/description/required/type参数是否存在，并且类型正确
                if not isinstance(parameter.get("name"), str):
                    raise ValidateException("parameter.name参数必须为字符串且不为空")
                if not isinstance(parameter.get("description"), str):
                    raise ValidateException("parameter.description参数必须为字符串且不为空")
                if not isinstance(parameter.get("required"), bool):
                    raise ValidateException("parameter.required参数必须为布尔值且不为空")
                if (
                        not isinstance(parameter.get("in"), str)
                        or parameter.get("in") not in ParameterIn.__members__.values()
                ):
                    raise ValidateException(f"parameter.in参数必须为{'/'.join([item.value for item in ParameterIn])}")
                if (
                        not isinstance(parameter.get("type"), str)
                        or parameter.get("type") not in ParameterType.__members__.values()
                ):
                    raise ValidateException(
                        f"parameter.type参数必须为{'/'.join([item.value for item in ParameterType])}")
            # 9、组装数据并更新
            extra_paths[interface["path"]] = {
                interface["method"]: {
                    "description": interface["operation"]["description"],
                    "operationId": interface["operation"]["operationId"],
                    "parameters": [{
                        "name": parameter["name"],
                        "in": parameter["in"],
                        "description": parameter["description"],
                        "required": parameter["required"],
                        "type": parameter["type"],
                    } for parameter in interface["operation"].get("parameters", [])],
                }
            }
        return extra_paths
