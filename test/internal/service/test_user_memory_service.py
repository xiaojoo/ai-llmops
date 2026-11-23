#!/usr/bin/env python
"""UserMemoryService 写侧管道测试：LLM 抽取用户特征（隐式更新判断）

service 经 container 工厂构造（真实 db_session），load_default_language_model
为 AsyncMock，方法全 await；db.session.add/flush/refresh → db_session 同 API + await。
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from internal.container import create_user_memory_service
from internal.model import UserMemoryFact
from internal.service.user_memory_service import ExtractedFact


class FakeExtractLLM:
    temperature = 0.0

    def __init__(self, reply):
        self.reply = reply

    def invoke(self, inputs):
        """Runnable 协议：被链调用"""
        return self.reply

    def __call__(self, inputs):
        return self.reply


class TestExtractUserFacts:
    @pytest.mark.asyncio
    async def test_extract_location_from_implicit_signals(self, db_session, monkeypatch):
        service = create_user_memory_service(db_session)
        raw = (
            '```json\n{"facts": [{"fact_key": "location", '
            '"fact_value": {"city": "北京"}, "confidence": 0.85, '
            '"is_implicit": true, "evidence": "用户询问北京天气并规划行程"}]}\n```'
        )
        monkeypatch.setattr(
            service.language_model_service, "load_default_language_model",
            AsyncMock(return_value=FakeExtractLLM(raw)),
        )

        facts = await service.extract_user_facts(
            "北京今天天气怎么样？帮我规划一下行程",
            "根据北京天气为您推荐了行程",
            "",
        )

        assert len(facts) == 1
        assert facts[0].fact_key == "location"
        assert facts[0].fact_value == {"city": "北京"}
        assert facts[0].is_implicit is True
        assert facts[0].confidence == 0.85

    def test_parse_garbage_returns_empty(self):
        service = create_user_memory_service(MagicMock())
        assert service._parse_facts("不是 JSON") == []
        assert service._parse_facts("") == []

    def test_parse_string_false_boolean_not_flipped(self):
        """回归：LLM 输出字符串布尔 "false" 不应被 bool() 翻转成 True"""
        service = create_user_memory_service(MagicMock())
        raw = ('{"facts": [{"fact_key": "location", "fact_value": {"city": "北京"}, '
               '"confidence": 0.8, "is_implicit": "false", "evidence": "x"}]}')
        facts = service._parse_facts(raw)
        assert len(facts) == 1
        assert facts[0].is_implicit is False


class TestWriteFactConflict:
    async def _add_fact(self, db_session, app_id, user_id, *, fact_key="location", value,
                        confidence, implicit, source, valid_to=None, tx_invalidated=None, valid_from=None):
        now = datetime.now()
        fact = UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key=fact_key,
            fact_value=value, source=source, trust_score=0.5,
            confidence=confidence, is_implicit=implicit,
            valid_from=valid_from or (now - timedelta(days=30)),
            valid_to=valid_to,
            tx_created_at=now - timedelta(days=30),
            tx_invalidated_at=tx_invalidated,
        )
        db_session.add(fact)
        await db_session.flush()
        return fact

    @pytest.mark.asyncio
    async def test_explicit_new_wins_over_old(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        old = await self._add_fact(db_session, app_id, user_id, value={"city": "深圳"},
                                   confidence=1.0, implicit=False, source="user_explicit")

        result = await service.write_fact(app_id, user_id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=1.0, is_implicit=False, evidence="用户明说搬去北京",
        ))

        assert result is not None and result.id != old.id, "显式新事实应插入新记录"
        await db_session.refresh(old)
        assert old.valid_to is not None, "旧事实应作废（保留历史）"
        assert old.tx_invalidated_at is not None, "旧事实应记录事务作废时间"
        current = await service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "北京"}

    @pytest.mark.asyncio
    async def test_implicit_low_confidence_rejected(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        old = await self._add_fact(db_session, app_id, user_id, value={"city": "深圳"},
                                   confidence=1.0, implicit=False, source="user_explicit")

        result = await service.write_fact(app_id, user_id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=0.6, is_implicit=True, evidence="询问北京天气",
        ))

        assert result is None, "低置信度隐式推断不应覆盖显式旧事实"
        await db_session.refresh(old)
        assert old.valid_to is None, "旧事实应保持不变"
        current = await service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "深圳"}

    @pytest.mark.asyncio
    async def test_implicit_high_confidence_wins(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        old = await self._add_fact(db_session, app_id, user_id, value={"city": "深圳"},
                                   confidence=0.7, implicit=True, source="llm_inferred")

        result = await service.write_fact(app_id, user_id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=0.9, is_implicit=True, evidence="连续询问北京天气并规划北京行程",
        ))

        assert result is not None, "高置信度隐式推断可覆盖低置信度旧推断"
        current = await service.get_current_fact(app_id, user_id, "location")
        assert current.fact_value == {"city": "北京"}

    @pytest.mark.asyncio
    async def test_same_value_merges_in_place(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        old = await self._add_fact(db_session, app_id, user_id, value={"city": "北京"},
                                   confidence=0.8, implicit=True, source="llm_inferred")

        result = await service.write_fact(app_id, user_id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=0.95, is_implicit=True, evidence="用户再次确认在北京",
        ))

        assert result is not None and result.id == old.id, "值相同应原地更新"
        await db_session.refresh(old)
        assert old.confidence == 0.95


class TestRetrieveFacts:
    @pytest.mark.asyncio
    async def test_current_facts_exclude_invalidated(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 当前有效
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        # 已作废历史
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "深圳"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now - timedelta(days=30), valid_to=now,
            tx_created_at=now - timedelta(days=30), tx_invalidated_at=now,
        ))
        await db_session.flush()

        current = await service.get_current_facts(app_id, user_id)
        history = await service.get_facts_history(app_id, user_id)
        past = await service.get_facts_at(app_id, user_id, now - timedelta(days=10))

        assert len(current) == 1 and current[0].fact_value == {"city": "北京"}
        assert len(history) == 2, "历史应含作废记录（审计）"
        assert len(past) == 1 and past[0].fact_value == {"city": "深圳"}, "时间点回溯应命中旧有效事实"

    @pytest.mark.asyncio
    async def test_current_facts_min_trust_filter(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 高信任显式事实
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="occupation",
            fact_value={"title": "工程师"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        # 低信任隐式推断
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="preference:reply_style",
            fact_value={"style": "简洁"}, source="llm_inferred",
            trust_score=0.3, confidence=0.6, is_implicit=True,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        await db_session.flush()

        all_facts = await service.get_current_facts(app_id, user_id)
        trusted = await service.get_current_facts(app_id, user_id, min_trust=0.8)

        assert len(all_facts) == 2, "默认 min_trust=0.0 应返回全部当前有效事实"
        assert len(trusted) == 1 and trusted[0].fact_key == "occupation", "min_trust 应过滤低信任事实"


class TestTtlExpiry:
    @pytest.mark.asyncio
    async def test_expire_overdue_facts(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 已过 valid_to 的事实
        promo = UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="promo",
            fact_value={"expired": True}, source="system",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now - timedelta(days=10), valid_to=now - timedelta(days=1),
            tx_created_at=now - timedelta(days=10), tx_invalidated_at=None,
        )
        db_session.add(promo)
        # 当前有效
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="user_explicit",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        await db_session.flush()

        count = await service.expire_overdue_facts(app_id, user_id)

        assert count == 1
        # 判别性断言：作废必须真实置位 tx_invalidated_at（而非仅查询命中）
        await db_session.refresh(promo)
        assert promo.tx_invalidated_at is not None, "过期事实应作废（tx_invalidated_at=now），保留历史而非删除"
        current = await service.get_current_facts(app_id, user_id)
        assert len(current) == 1, "过期事实作废后不再进入当前有效集合"

    @pytest.mark.asyncio
    async def test_min_trust_filter(self, db_session):
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="location",
            fact_value={"city": "北京"}, source="llm_inferred",
            trust_score=0.2, confidence=0.9, is_implicit=True,
            valid_from=now, valid_to=None,
            tx_created_at=now, tx_invalidated_at=None,
        ))
        await db_session.flush()

        all_facts = await service.get_current_facts(app_id, user_id)
        trusted = await service.get_current_facts(app_id, user_id, min_trust=0.5)

        assert len(all_facts) == 1
        assert len(trusted) == 0, "低信任事实应按 min_trust 过滤"


class TestWindowRetrieval:
    """通告类事实的时间窗口检索测试（现实视角，不看 tx_invalidated_at）"""

    async def _add_fact(self, db_session, app_id, user_id, fact_key, value, valid_from, valid_to):
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key=fact_key,
            fact_value=value, source="system",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=valid_from, valid_to=valid_to,
            tx_created_at=valid_from, tx_invalidated_at=None,
        ))
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_get_facts_in_window_overlap(self, db_session):
        """通告：7月有效 / 8月有效 / 长期有效，查询窗口 [7/15, 8/15] 应命中前两条"""
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        july_start = datetime(now.year, 7, 1)
        aug_end = datetime(now.year, 8, 31)
        await self._add_fact(db_session, app_id, user_id, "notice:july",
                             {"title": "7月通告"}, july_start, datetime(now.year, 7, 31))
        await self._add_fact(db_session, app_id, user_id, "notice:aug",
                             {"title": "8月通告"}, datetime(now.year, 8, 1), aug_end)
        await self._add_fact(db_session, app_id, user_id, "notice:always",
                             {"title": "长期通告"}, datetime(now.year, 1, 1), None)

        window = await service.get_facts_in_window(
            app_id, user_id,
            datetime(now.year, 7, 15), datetime(now.year, 8, 15),
        )

        titles = {f.fact_key for f in window}
        assert "notice:july" in titles, "7月通告与窗口重叠应命中"
        assert "notice:aug" in titles, "8月通告与窗口重叠应命中"
        assert "notice:always" in titles, "长期有效（valid_to=NULL）通告应命中"
        assert len(window) == 3

    @pytest.mark.asyncio
    async def test_get_facts_in_window_no_overlap(self, db_session):
        """通告已结束：查询窗口在 valid_to 之后不应命中"""
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        await self._add_fact(db_session, app_id, user_id, "notice:old",
                             {"title": "已结束通告"}, datetime(now.year, 1, 1), datetime(now.year, 1, 31))

        window = await service.get_facts_in_window(
            app_id, user_id,
            datetime(now.year, 3, 1), datetime(now.year, 3, 31),
        )

        assert len(window) == 0, "查询窗口在 valid_to 之后不应命中已结束通告"

    @pytest.mark.asyncio
    async def test_get_facts_in_window_ignores_tx_invalidated(self, db_session):
        """作废（tx_invalidated_at 置位）不影响现实时间窗口检索"""
        service = create_user_memory_service(db_session)
        app_id, user_id = uuid4(), uuid4()
        now = datetime.now()
        # 已作废的通告（被新版本替换），但现实世界时间窗口仍为真
        db_session.add(UserMemoryFact(
            app_id=app_id, user_id=user_id, fact_key="notice:v1",
            fact_value={"title": "V1通告"}, source="system",
            trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=datetime(now.year, 6, 1), valid_to=datetime(now.year, 9, 30),
            tx_created_at=datetime(now.year, 6, 1),
            tx_invalidated_at=datetime(now.year, 8, 1),  # 8月被系统作废（被 V2 替换）
        ))
        await db_session.flush()

        window = await service.get_facts_in_window(
            app_id, user_id,
            datetime(now.year, 7, 1), datetime(now.year, 7, 31),
        )

        assert len(window) == 1, "现实视角窗口检索应忽略系统作废时间，V1 在 7 月仍命中"
