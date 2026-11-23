"""回填存量预签名 URL → 永久公开 URL（一次性数据修复）。

背景：MinIO 模式下早期上传把 mall 返回的预签名 URL（7 天过期）原样落库
（upload_file.key / account.avatar / app.icon / dataset.icon / skill.icon /
skill.archive_url / message.file_urls / message.image_urls / message_agent_thought.message），
过期后前端访问 403。存储桶为公开读，剥掉 ?X-Amz 签名参数即为永久公开 URL。

安全：仅处理含 ?X-Amz 的行；JSONB 列递归剥除所有字符串值中的签名参数。
幂等：可重复执行（已剥的行不再命中 LIKE '%?X-Amz%'）。
"""
import json
import re
import sys

sys.path.insert(0, ".")
import dotenv

dotenv.load_dotenv()

from sqlalchemy import text

from package.database import get_sync_engine


def _strip(v):
    """递归剥除字符串值中的预签名查询参数（?X-Amz... 直至空白/结尾）。"""
    if isinstance(v, str):
        return re.sub(r"\?X-Amz[^\s]*", "", v)
    if isinstance(v, list):
        return [_strip(x) for x in v]
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items()}
    return v


# (表, 列) —— 文本/字符串列（值为单个 URL）
TEXT_COLUMNS = [
    ("account", "avatar"),
    ("app", "icon"),
    ("dataset", "icon"),
    ("skill", "archive_url"),
    ("skill", "icon"),
    ("upload_file", "key"),
]
# (表, 列) —— JSONB 列（需递归处理）
JSONB_COLUMNS = [
    ("message", "file_urls"),
    ("message", "image_urls"),
    ("message_agent_thought", "message"),
]


def main() -> None:
    eng = get_sync_engine()
    total = 0
    with eng.begin() as c:
        for table, col in TEXT_COLUMNS:
            rows = c.execute(
                text(f'SELECT id, "{col}" FROM "{table}" WHERE "{col}" LIKE \'%?X-Amz%\'')
            ).fetchall()
            for rid, val in rows:
                new_val = _strip(val)
                c.execute(
                    text(f'UPDATE "{table}" SET "{col}" = :v WHERE id = :id'),
                    {"v": new_val, "id": rid},
                )
            if rows:
                print(f"{table}.{col}: {len(rows)} rows fixed")
            total += len(rows)
        for table, col in JSONB_COLUMNS:
            rows = c.execute(
                text(f'SELECT id, "{col}" FROM "{table}" WHERE "{col}"::text LIKE \'%?X-Amz%\'')
            ).fetchall()
            for rid, val in rows:
                new_val = _strip(val)
                c.execute(
                    text(f'UPDATE "{table}" SET "{col}" = CAST(:v AS jsonb) WHERE id = :id'),
                    {"v": json.dumps(new_val, ensure_ascii=False), "id": rid},
                )
            if rows:
                print(f"{table}.{col}: {len(rows)} rows fixed")
            total += len(rows)
    print(f"total fixed: {total}")


if __name__ == "__main__":
    main()
