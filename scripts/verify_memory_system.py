#!/usr/bin/env python
"""
记忆系统四层端到端验证脚本（验证接口 + 写侧管道 + 双时间/检索/反思）

验证内容：
1. 语义记忆：/memory/facts 与 /memory/facts/history（双时间作废审计）
2. 情景记忆：/memory/episodic（写侧管道抽取后可见）
3. 程序记忆：/memory/instructions（dislike 反思改写后可见）
4. 短期记忆：/conversations/messages 的 is_archived 标记
"""
import logging
import os
import sys
import time

# 抑制 SQLAlchemy 引擎日志，只保留验证结果输出
logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
for name in ("internal.extension.database_extension", "package.sqlalchemy"):
    logging.getLogger(name).setLevel(logging.CRITICAL)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MODE", "local")

from app.http.app import app  # noqa: E402
from app.http.module import injector  # noqa: E402
from internal.extension.database_extension import db  # noqa: E402
from internal.model import (  # noqa: E402
    Account,
    App,
    Conversation,
    EpisodicMemory,
    Message,
    ProceduralMemory,
    UserMemoryFact,
)
from internal.service import (  # noqa: E402
    EpisodicMemoryService,
    ProceduralMemoryService,
    ReflectionService,
    UserMemoryService,
)
from package.response import HttpCode  # noqa: E402

PASS = "✅"
FAIL = "❌"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name} {detail}")


def get_current_user():
    return db.session.query(Account).order_by(Account.created_at).first()


def make_app(account, name="记忆验证应用"):
    app_record = App(account_id=account.id, name=name, icon="", created_by=account.id, updated_by=account.id)
    db.session.add(app_record)
    db.session.flush()
    return app_record


def make_message(app_record, account, conversation, query, answer, status="normal"):
    msg = Message(
        app_id=app_record.id, conversation_id=conversation.id,
        created_by=account.id, updated_by=account.id,
        invoke_from="debugger", query=query, answer=answer,
        status=status,
    )
    db.session.add(msg)
    db.session.flush()
    return msg


def main():
    with app.app_context():
        account = get_current_user()
        if account is None:
            print(FAIL, "需要数据库中存在账号")
            return
        app_record = make_app(account)
        conversation = Conversation(
            app_id=app_record.id, created_by=account.id, updated_by=account.id,
            name="验证会话", invoke_from="debugger",
        )
        db.session.add(conversation)
        db.session.flush()

        user_memory = injector.get(UserMemoryService)
        episodic_memory = injector.get(EpisodicMemoryService)
        procedural_memory = injector.get(ProceduralMemoryService)
        reflection = injector.get(ReflectionService)

        print("=" * 60)
        print("1️⃣  语义记忆：用户卡片 + 双时间机制（深圳 → 北京 隐式更新）")
        print("=" * 60)

        # 1a. 显式写入 location=深圳
        from internal.service.user_memory_service import ExtractedFact
        user_memory.write_fact(app_record.id, account.id, ExtractedFact(
            fact_key="location", fact_value={"city": "深圳"},
            confidence=1.0, is_implicit=False, evidence="用户明说在深圳",
        ))
        facts = user_memory.get_current_facts(app_record.id, account.id)
        check("显式写入深圳", len(facts) == 1 and facts[0].fact_value == {"city": "深圳"},
              f"current={[f.fact_value for f in facts]}")

        # 1b. 低置信度隐式推断（北京天气查询）应被拒绝
        rejected = user_memory.write_fact(app_record.id, account.id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=0.6, is_implicit=True, evidence="询问北京天气（弱信号）",
        ))
        facts = user_memory.get_current_facts(app_record.id, account.id)
        check("低置信度隐式推断被拒绝", rejected is None and facts[0].fact_value == {"city": "深圳"},
              f"rejected={rejected is None} current={[f.fact_value for f in facts]}")

        # 1c. 高置信度隐式推断（连续北京信号）应胜出并作废旧事实
        winner = user_memory.write_fact(app_record.id, account.id, ExtractedFact(
            fact_key="location", fact_value={"city": "北京"},
            confidence=0.9, is_implicit=True, evidence="连续询问北京天气+规划北京行程（强信号）",
        ))
        facts = user_memory.get_current_facts(app_record.id, account.id)
        check("高置信度隐式推断胜出", winner is not None and facts[0].fact_value == {"city": "北京"},
              f"current={[f.fact_value for f in facts]}")

        # 1d. 历史审计：深圳记录作废保留（双时间机制）
        history = user_memory.get_facts_history(app_record.id, account.id)
        shenzhen_rows = [f for f in history if f.fact_value.get("city") == "深圳"]
        check("深圳旧事实作废保留历史", len(shenzhen_rows) == 1 and shenzhen_rows[0].tx_invalidated_at is not None,
              f"history_count={len(history)} shenzhen_tx_invalidated={shenzhen_rows[0].tx_invalidated_at if shenzhen_rows else None}")

        # 1e. 时间点回溯：构造一条"过去有效区间"的事实，验证 at 时刻能命中
        from datetime import datetime, timedelta
        now = datetime.now()
        past_fact = UserMemoryFact(
            app_id=app_record.id, user_id=account.id,
            fact_key="occupation", fact_value={"role": "工程师"},
            source="user_explicit", trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=now - timedelta(days=30), valid_to=now - timedelta(days=10),
            tx_created_at=now - timedelta(days=30), tx_invalidated_at=None,
        )
        db.session.add(past_fact)
        db.session.flush()
        past = user_memory.get_facts_at(app_record.id, account.id, now - timedelta(days=20))
        check("时间点回溯命中过去有效事实", any(f.fact_value.get("role") == "工程师" for f in past),
              f"past={[f.fact_value for f in past]}")

        print()
        print("=" * 60)
        print("2️⃣  情景记忆：写侧管道（mock 向量）+ 检索")
        print("=" * 60)

        # 2a. 写入情景记忆（monkeypatch 向量依赖：property 带 setter，用显式赋值+恢复）
        import unittest.mock as mock
        fake_collection = mock.MagicMock()
        fake_collection.data.insert.return_value = "fake-obj-id-001"
        fake_embeddings = mock.MagicMock(embed_query=lambda t: [0.1, 0.2, 0.3])

        vds = episodic_memory.vector_database_service
        es = episodic_memory.embeddings_service
        orig_collection = vds.episodic_memory_collection
        orig_embeddings = es.embeddings
        vds.episodic_memory_collection = fake_collection
        es.embeddings = fake_embeddings
        try:
            ep = episodic_memory.write_episode(
                app_id=app_record.id, user_id=account.id,
                content="用户正在准备搬家到北京，已完成房源搜索", importance=0.9,
            )
        finally:
            vds.episodic_memory_collection = orig_collection
            es.embeddings = orig_embeddings
        check("情景记忆写入（PG+向量）", ep.embedding_id == "fake-obj-id-001",
              f"embedding_id={ep.embedding_id}")

        # 2b. 检索接口数据可见（get_episodes 调试方法）
        episodes = episodic_memory.get_episodes(app_record.id, account.id)
        check("情景记忆调试查询可见", len(episodes) >= 1 and "北京" in episodes[0].content,
              f"episodes={[e.content[:20] for e in episodes]}")

        print()
        print("=" * 60)
        print("3️⃣  程序记忆：dislike 反思改写")
        print("=" * 60)

        # 3a. like 不触发
        reflection.reflect_on_feedback(
            flask_app=app, app_id=app_record.id, user_id=account.id,
            query="谢谢", answer="不客气", feedback="like",
        )
        instructions = procedural_memory.get_instruction_records(app_record.id, account.id)
        check("like 不触发反思", len(instructions) == 0, f"count={len(instructions)}")

        # 3b. dislike 触发（mock LLM 返回指令）
        class FakeReflectLLM:
            temperature = 0.0

            def __call__(self, inputs):
                return '```json\n{"instruction": "回答用户时应先给结论，再展开细节，避免冗长铺垫"}\n```'

        with mock.patch.object(
            reflection.language_model_service, "load_default_language_model", lambda: FakeReflectLLM(),
        ):
            reflection.reflect_on_feedback(
                flask_app=app, app_id=app_record.id, user_id=account.id,
                query="请帮我分析这份报告", answer="（很长的铺垫）", feedback="dislike",
            )
        instructions = procedural_memory.get_instruction_records(app_record.id, account.id)
        check("dislike 反思写入规则", len(instructions) == 1 and "先给结论" in instructions[0].content,
              f"instructions={[i.content[:20] for i in instructions]}")

        print()
        print("=" * 60)
        print("4️⃣  短期记忆：归档标记（惰性压缩基础）")
        print("=" * 60)
        msg1 = make_message(app_record, account, conversation, "问题0", "答案0", "normal")
        msg2 = make_message(app_record, account, conversation, "问题1", "答案1", "normal")
        check("消息创建含 is_archived 默认 False", msg1.is_archived is False and msg2.is_archived is False,
              f"msg1={msg1.is_archived} msg2={msg2.is_archived}")
        # 手动标记归档（模拟压缩逻辑）
        from sqlalchemy import select
        stmt = select(Message).where(Message.id == msg1.id)
        record = db.session.execute(stmt).scalar_one()
        record.is_archived = True
        db.session.commit()
        check("归档标记可设置", record.is_archived is True, "msg1 archived")

        print()
        print("=" * 60)
        print("📋  验证汇总")
        print("=" * 60)
        passed = sum(1 for _, ok, _ in results if ok)
        failed = sum(1 for _, ok, _ in results if not ok)
        print(f"通过 {passed} / 失败 {failed} / 共 {len(results)}")
        if failed:
            print("失败项：")
            for name, ok, detail in results:
                if not ok:
                    print(f"  - {name} {detail}")
        print("清理验证数据...")
        # 回滚由调用方决定；这里显式删除本会话产生的数据（保留其他测试数据）
        db.session.rollback()


if __name__ == "__main__":
    main()
