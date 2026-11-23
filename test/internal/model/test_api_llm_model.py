import pytest
from sqlalchemy import select

from internal.model import ApiLlmModel
from package.database import Base


@pytest.mark.asyncio
async def test_api_llm_model_table_create_and_read(db_session):
    # The api_llm_model table may not exist yet (Alembic migration is a later task);
    # create it self-contained within the db_session transaction (rolled back on teardown).
    conn = await db_session.connection()
    await conn.run_sync(Base.metadata.create_all, tables=[ApiLlmModel.__table__])

    record = ApiLlmModel(
        account_id="11111111-1111-1111-1111-111111111111",
        name="My Claude",
        protocol="anthropic",
        model_id="claude-3-5-sonnet",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xxxx",
        features=["tool_call", "agent_thought"],
        context_window=200000,
        max_output_tokens=8192,
        remark="test",
        icon="https://example.com/a.png",
    )
    db_session.add(record)
    await db_session.commit()

    stmt = select(ApiLlmModel).where(ApiLlmModel.name == "My Claude")
    result = (await db_session.execute(stmt)).scalars().first()
    assert result is not None
    assert result.protocol == "anthropic"
    assert result.features == ["tool_call", "agent_thought"]
