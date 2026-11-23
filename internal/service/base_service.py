#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/28 18:17
@Author : sunxiaojie
@File   : base_service.py
"""
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from internal.exception import FailedException

T = TypeVar("T")


@dataclass
class BaseService:
    """基础服务，完善数据库的基础增删改查功能，简化代码。

    事务模型：create/update/delete 为**独立事务边界**——块尾真实 `await self.db.commit()`
    （保证 id 生成、立即持久化与请求→后台可见性）；异常回滚由外层（get_db / worker_run）兜底。
    """

    db: AsyncSession

    async def create(self, model: type[T], **kwargs) -> T:
        """根据传递的模型类+键值对信息创建数据库记录。

        AsyncSession.add 是同步方法，**不 await**（await 同步方法会抛 TypeError）。
        """
        model_instance = model(**kwargs)
        self.db.add(model_instance)
        await self.db.commit()  # 独立事务边界
        return model_instance

    async def delete(self, model_instance: T) -> T:
        """根据传递的模型实例删除数据库记录。

        AsyncSession.delete 是协程，**必须 await**（未 await 则删除不生效且产生未消费协程）。
        """
        await self.db.delete(model_instance)
        await self.db.commit()  # 独立事务边界
        return model_instance

    async def update(self, model_instance: T, **kwargs) -> T:
        """根据传递的模型实例+键值对信息更新数据库记录"""
        # TODO1: 有隐患
        self.db.add(model_instance)
        for field, value in kwargs.items():
            if hasattr(model_instance, field):
                setattr(model_instance, field, value)
            else:
                raise FailedException("更新数据失败")
        await self.db.commit()  # 独立事务边界
        return model_instance

    async def get(self, model: type[T], primary_key: Any) -> T | None:
        """根据传递的模型类+主键的信息获取唯一数据"""
        # return self.db.session.query(model).get(primary_key)
        return await self.db.get(model, primary_key)
