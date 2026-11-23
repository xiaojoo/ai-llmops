#!/usr/bin/env python
"""
@Time    : 2026/2/7 19:41
@Author  : sunxiaojie
@File    : analysis_service.py
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from redis import Redis
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.model import Account, App, Message

from .app_service import AppService
from .base_service import BaseService


@dataclass
class AnalysisService(BaseService):
    """统计分析服务"""
    db: AsyncSession
    redis_client: Redis
    app_service: AppService

    async def get_app_analysis(self, app_id: UUID, account: Account) -> dict[str, Any]:
        """根据传递的应用id+账号获取指定应用的分析信息"""
        # 1、获取应用信息并校验权限
        app = await self.app_service.get_app(app_id, account)

        # 2、获取核心时间点
        today = datetime.now()
        today_midnight = datetime.combine(today, datetime.min.time())
        seven_days_ago = today_midnight - timedelta(days=7)
        fourteen_days_ago = today_midnight - timedelta(days=14)

        # 3、缓存处理
        cache_key = f"{today.strftime('%Y_%m_%d')}:{app.id!s}"
        try:
            if self.redis_client.exists(cache_key):
                app_analysis = self.redis_client.get(cache_key)
                if app_analysis is not None:
                    return json.loads(app_analysis)
        except Exception:
            pass

        # 4、获取最近 7 天和 14-7 天的汇总数据（Row对象）
        seven_days_row = await self.get_messages_by_time_range(app, seven_days_ago, today_midnight)
        fourteen_days_row = await self.get_messages_by_time_range(app, fourteen_days_ago, seven_days_ago)

        # 5、计算指标字典
        seven_overview_indicators = self.calculate_overview_indicators_by_messages(seven_days_row)
        fourteen_overview_indicators = self.calculate_overview_indicators_by_messages(fourteen_days_row)

        # 6、计算环比增长
        pop = self.calculate_pop_by_overview_indicators(seven_overview_indicators, fourteen_overview_indicators)

        # 7、计算趋势（采用单次 SQL 查询分组聚合的主流方案）
        trend = await self.calculate_trend_by_messages(app, seven_days_ago, today_midnight)

        # 8、构建响应结构
        fields = [
            "total_messages", "active_accounts", "avg_of_conversation_messages",
            "token_output_rate", "cost_consumption",
        ]

        app_analysis = {
            **trend,
            **{
                field: {
                    "data": seven_overview_indicators.get(field),
                    "pop": pop.get(field),
                } for field in fields
            }
        }

        # 9、异步更新缓存，设置过期时间 1 天
        try:
            self.redis_client.set(cache_key, json.dumps(app_analysis), ex=86400)
        except Exception:
            pass

        return app_analysis

    async def get_messages_by_time_range(self, app: App, start_at: datetime, end_at: datetime):
        """获取指定时间段内应用的消息统计汇总"""
        stmt = select(
            func.count(Message.id).label("total_messages"),
            func.count(func.distinct(Message.created_by)).label("active_accounts"),
            func.count(func.distinct(Message.conversation_id)).label("conversation_count"),
            func.coalesce(func.sum(Message.total_token_count), 0).label("total_tokens"),
            func.coalesce(func.sum(Message.latency), 0).label("latency_sum"),
            cast(func.coalesce(func.sum(Message.total_price), 0), Float).label("cost_consumption"),
        ).where(
            Message.app_id == app.id,
            Message.created_at >= start_at,
            Message.created_at < end_at,
            Message.answer != ""
        )

        return (await self.db.execute(stmt)).one()

    async def calculate_trend_by_messages(self, app: App, start_at: datetime, end_at: datetime) -> dict[str, Any]:
        """主流方法：使用 SQL 分组聚合一次性查询 7 天趋势数据，并在 Python 中补全 0 数据"""
        # 1、定义按日期分组的查询
        day_column = func.date(Message.created_at).label("day")
        stmt = select(
            day_column,
            func.count(Message.id).label("total_messages"),
            func.count(func.distinct(Message.created_by)).label("active_accounts"),
            func.count(func.distinct(Message.conversation_id)).label("conversation_count"),
            cast(func.coalesce(func.sum(Message.total_price), 0), Float).label("cost_consumption"),
        ).where(
            Message.app_id == app.id,
            Message.created_at >= start_at,
            Message.created_at < end_at,
            Message.answer != ""
        ).group_by(day_column).order_by(day_column)

        results = (await self.db.execute(stmt)).all()

        # 2、将查询结果转换为字典，Key 为日期字符串，方便 O(1) 查找
        data_map = {str(r.day): r for r in results}

        # 3、初始化返回结构
        trends = {
            "total_messages_trend": {"x_axis": [], "y_axis": []},
            "active_accounts_trend": {"x_axis": [], "y_axis": []},
            "avg_of_conversation_messages_trend": {"x_axis": [], "y_axis": []},
            "cost_consumption_trend": {"x_axis": [], "y_axis": []},
        }

        # 4、循环补全 7 天内每一天的数据（即使某天没有消息也填充 0）
        current_day = start_at
        while current_day < end_at:
            day_str = current_day.strftime("%Y-%m-%d")
            timestamp = int(current_day.timestamp())
            row = data_map.get(day_str)

            # 提取数据
            total_msgs = row.total_messages if row else 0
            active_accounts = row.active_accounts if row else 0
            conv_count = row.conversation_count if row else 0
            cost = float(row.cost_consumption) if row else 0.0
            avg_msgs = (total_msgs / conv_count) if conv_count > 0 else 0.0

            # 填充各指标轴
            trends["total_messages_trend"]["x_axis"].append(timestamp)
            trends["total_messages_trend"]["y_axis"].append(total_msgs)

            trends["active_accounts_trend"]["x_axis"].append(timestamp)
            trends["active_accounts_trend"]["y_axis"].append(active_accounts)

            trends["avg_of_conversation_messages_trend"]["x_axis"].append(timestamp)
            trends["avg_of_conversation_messages_trend"]["y_axis"].append(float(avg_msgs))

            trends["cost_consumption_trend"]["x_axis"].append(timestamp)
            trends["cost_consumption_trend"]["y_axis"].append(cost)

            current_day += timedelta(days=1)

        return trends

    @classmethod
    def calculate_overview_indicators_by_messages(cls, row) -> dict[str, Any]:
        """根据汇总 Row 计算概览指标"""
        total_messages = row.total_messages or 0
        active_accounts = row.active_accounts or 0
        conversation_count = row.conversation_count or 0
        latency_sum = row.latency_sum or 0
        total_tokens = row.total_tokens or 0
        cost_consumption = float(row.cost_consumption or 0)

        avg_of_conversation_messages = (
            total_messages / conversation_count
            if conversation_count else 0
        )

        token_output_rate = (
            total_tokens / latency_sum
            if latency_sum else 0
        )

        return {
            "total_messages": total_messages,
            "active_accounts": active_accounts,
            "avg_of_conversation_messages": float(avg_of_conversation_messages),
            "token_output_rate": float(token_output_rate),
            "cost_consumption": float(cost_consumption),
        }

    @classmethod
    def calculate_pop_by_overview_indicators(
            cls,
            current_data: dict[str, Any],
            previous_data: dict[str, Any]
    ) -> dict[str, Any]:
        """计算环比增长"""
        pop = {}
        fields = [
            "total_messages", "active_accounts", "avg_of_conversation_messages",
            "token_output_rate", "cost_consumption",
        ]

        for field in fields:
            current_value = current_data.get(field, 0)
            previous_value = previous_data.get(field, 0)

            if previous_value != 0:
                pop[field] = (current_value - previous_value) / previous_value
            else:
                pop[field] = 0.0

        return pop
