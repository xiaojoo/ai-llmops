#!/usr/bin/env python
"""通告时间线 + 状态标记演示（真实 DB）"""
import sys, logging
sys.path.insert(0, r'H:\ai-code-llmops')
logging.disable(logging.CRITICAL)
from datetime import datetime

from app.http.app import app
from app.http.module import injector
from internal.extension.database_extension import db
from internal.model import Account, App, UserMemoryFact
from internal.schema.user_memory_schema import UserMemoryFactResp
from internal.service import UserMemoryService

with app.app_context():
    account = db.session.query(Account).first()
    a = App(account_id=account.id, name="时间线状态演示", icon="", created_by=account.id, updated_by=account.id)
    db.session.add(a)
    db.session.flush()
    svc = injector.get(UserMemoryService)
    aid, uid = a.id, account.id
    now = datetime.now()
    y = now.year

    versions = [
        ("notice:promo", "夏季促销V1", datetime(y, 6, 1), datetime(y, 6, 30)),
        ("notice:promo", "夏季促销V2", datetime(y, 7, 1), datetime(y, 9, 30)),
        ("notice:promo", "夏季促销V3", datetime(y, 10, 1), datetime(y, 12, 31)),
    ]
    for key, title, vf, vt in versions:
        db.session.add(UserMemoryFact(
            app_id=aid, user_id=uid, fact_key=key, fact_value={"title": title},
            source="system", trust_score=1.0, confidence=1.0, is_implicit=False,
            valid_from=vf, valid_to=vt, tx_created_at=vf, tx_invalidated_at=None,
        ))
    db.session.flush()

    resp = UserMemoryFactResp(many=True)
    print("--- 通告时间线（历史全版本 + 状态）---")
    for item in resp.dump(svc.get_facts_history(aid, uid)):
        span = f"{str(item['valid_from'])[:10]} -> {str(item['valid_to'])[:10] or '长期'}"
        print(f"  {item['fact_value']['title']:<10} {span:<28} 状态={item['status']}")

    print("--- 窗口 [8/1, 8/31]（V1过期、V3未开始，应只命中V2）---")
    win = svc.get_facts_in_window(aid, uid, datetime(y, 8, 1), datetime(y, 8, 31))
    for item in resp.dump(win):
        print(f"  {item['fact_value']['title']:<10} 状态={item['status']}")
    db.session.rollback()
