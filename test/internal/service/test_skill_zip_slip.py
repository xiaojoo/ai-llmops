import io
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.exception import ValidateException
from internal.service.skill_service import SkillService


@pytest.mark.asyncio
async def test_skill_zip_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        SkillService,
        "_cache_dir",
        staticmethod(lambda _skill_id: tmp_path / "cache"),
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.execute.return_value.scalars.return_value.first.return_value = None
    service = SkillService(db=db, minio_service=MagicMock())
    service.create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    service._archive_bytes = MagicMock(return_value="")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: demo\ndescription: demo\n---\n")
        archive.writestr("../escape.txt", "bad")

    with pytest.raises(ValidateException) as exc_info:
        await service.upload_zip(
            SimpleNamespace(id=uuid.uuid4()),
            "demo.zip",
            buffer.getvalue(),
        )
    assert "越界路径" in exc_info.value.message
    assert not (tmp_path / "escape.txt").exists()


def test_restore_skill_zip_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        SkillService,
        "_cache_dir",
        staticmethod(lambda _skill_id: tmp_path / "cache"),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: demo\ndescription: demo\n---\n")
        archive.writestr("../escape.txt", "bad")
    response = MagicMock(status_code=200, content=buffer.getvalue())
    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: response)
    service = SkillService(db=MagicMock(), minio_service=MagicMock())

    service._restore_cache_from_archive(SimpleNamespace(
        id=uuid.uuid4(), archive_url="https://example.com/skill.zip",
    ))
    assert not (tmp_path / "escape.txt").exists()
    cache = tmp_path / "cache"
    assert not cache.exists() or not any(cache.rglob("*"))
