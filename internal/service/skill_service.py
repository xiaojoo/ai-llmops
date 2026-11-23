#!/usr/bin/env python
"""
@Time    : 2026/3/20 18:32
@Author  : sunxiaojie
@File    : skill_service.py

技能服务：
- 上传（.md / .zip）即解压/保存到本地缓存目录 storage/skills/{skill_id}/，同时归档原始文件到 MinIO
- 入口 SKILL.md 正文入库（content 字段），预览与构建 LangChain 工具直接从 DB 读取
- 用户隔离：account_id 归属 + visibility（private 独占 / public 分享）
"""
import io
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.entity.skill_entity import FRONTMATTER_RE
from internal.exception import FailedException, NotFoundException, ValidateException
from internal.model import Account, Skill
from internal.schema.upload_skill_schema import GetSkillListWithPageReq
from internal.service import MinioService
from package.paginator import Paginator

from .base_service import BaseService

# 本地技能缓存根目录（上传即解压到此处，运行期直接读取，不依赖 MinIO）
SKILL_CACHE_ROOT = Path("storage/skills")


@dataclass
class SkillService(BaseService):
    db: AsyncSession
    minio_service: MinioService

    # ==================== 上传 ====================

    async def upload(self, current_user: Account, content: str, icon: str = "") -> Skill:
        """上传单 .md 技能：正文入库 + 本地缓存 + MinIO 归档"""
        meta = self._parse_frontmatter(content)
        skill_id = uuid.uuid4()

        # 1、校验同名技能（当前用户维度）
        existing = (await self.db.execute(
            select(Skill).where(
                Skill.account_id == current_user.id,
                Skill.name == meta["name"],
            )
        )).scalars().first()
        if existing:
            raise FailedException(f"技能 '{meta['name']}' 已存在")

        # 2、本地缓存 SKILL.md（运行期读取）
        cache_dir = self._cache_dir(skill_id)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "SKILL.md").write_text(content, encoding="utf-8")
        except OSError as e:
            shutil.rmtree(cache_dir, ignore_errors=True)
            raise FailedException(f"技能文件保存失败: {e}")

        # 3、归档原始 .md 到 MinIO（失败不影响入库，仅记录）
        archive_url = self._archive_bytes(
            content.encode("utf-8"), f"{meta['name']}.md", f"{current_user.id}"
        )

        # 4、写入数据库
        try:
            skill = await self.create(
                Skill,
                id=skill_id,
                account_id=current_user.id,
                name=meta["name"],
                description=meta["description"],
                icon=icon,
                visibility="private",
                content=content,
                archive_url=archive_url,
                created_by=str(current_user.id),
                updated_by=str(current_user.id),
            )
        except Exception:
            shutil.rmtree(cache_dir, ignore_errors=True)
            raise
        return skill

    async def upload_zip(self, current_user: Account, filename: str, file_bytes: bytes, icon: str = "") -> list[Skill]:
        """上传 .zip 技能包：一个 zip = 一个技能

        - 技能名取 zip 文件名（去 .zip 后缀）
        - 入口 SKILL.md：优先 zip 根目录，否则取包内第一个 SKILL.md
        - 全部文件（含子目录）保留结构解压到 storage/skills/{skill_id}/，去掉公共根前缀
        """
        # 1、校验是否为合法 zip
        if not zipfile.is_zipfile(io.BytesIO(file_bytes)):
            raise ValidateException("上传的文件不是合法的 zip 压缩包")

        # 2、技能名 = zip 文件名（去 .zip）
        skill_name = (filename or "skill").rsplit(".", 1)[0].strip() or "skill"
        if not skill_name:
            raise ValidateException("技能名称不能为空")

        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
            all_members = [name for name in zf.namelist() if not name.endswith("/")]

            # 3、找入口 SKILL.md：优先根目录，否则层级最浅的第一个
            skill_md_paths = [name for name in all_members if name.endswith("SKILL.md")]
            if not skill_md_paths:
                raise ValidateException("压缩包中未找到 SKILL.md 文件")
            root_md = next((p for p in skill_md_paths if "/" not in p), None)
            if root_md:
                entry_md_path = root_md
            else:
                # 取层级最浅（目录段最少）的第一个，稳定排序
                entry_md_path = sorted(skill_md_paths, key=lambda p: p.count("/"))[0]

            # 4、读取入口 SKILL.md 内容
            try:
                content = zf.read(entry_md_path).decode("utf-8")
            except UnicodeDecodeError:
                raise ValidateException(f"{entry_md_path} 编码错误，请使用 UTF-8 格式")

            # 5、解析 Front Matter（description 取入口文件，name 用 zip 文件名）
            meta = self._parse_frontmatter(content)

            # 6、检查同名技能是否已存在（当前用户维度）
            existing = (await self.db.execute(
                select(Skill).where(
                    Skill.account_id == current_user.id,
                    Skill.name == skill_name,
                )
            )).scalars().first()
            if existing:
                raise FailedException(f"技能 '{skill_name}' 已存在")

            # 7、计算公共根前缀：zip 内所有文件共有的最顶层目录（如 superpowers/ 或 skills/）
            #    解压时去掉该前缀，保留其余相对结构
            top_dirs = {p.split("/", 1)[0] for p in all_members if "/" in p}
            common_root = ""
            if len(top_dirs) == 1:
                only = next(iter(top_dirs))
                # 仅当入口文件也在该顶层目录下时，才视为公共根（避免把入口在根、其余在子目录的包误剥）
                if entry_md_path.startswith(only + "/"):
                    common_root = only + "/"

            # 8、本地解压缓存到 storage/skills/{skill_id}/
            skill_id = uuid.uuid4()
            cache_dir = self._cache_dir(skill_id)
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                for member in all_members:
                    relative = member[len(common_root):] if common_root else member
                    if not relative:
                        continue
                    target = cache_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
            except OSError as e:
                shutil.rmtree(cache_dir, ignore_errors=True)
                raise FailedException(f"文件解压失败: {e}")

        # 9、归档原始 zip 到 MinIO（失败不影响入库）
        archive_url = self._archive_bytes(file_bytes, filename or f"{skill_name}.zip", f"{current_user.id}")

        # 10、写入数据库
        try:
            skill = await self.create(
                Skill,
                id=skill_id,
                account_id=current_user.id,
                name=skill_name,
                description=meta["description"],
                icon=icon,
                visibility="private",
                content=content,
                archive_url=archive_url,
                created_by=str(current_user.id),
                updated_by=str(current_user.id),
            )
        except Exception:
            shutil.rmtree(cache_dir, ignore_errors=True)
            raise

        return [skill]

    # ==================== 查询 ====================

    async def get_skill_list_with_page(
        self, req: GetSkillListWithPageReq, current_user: Account
    ) -> tuple[list[Skill], Paginator]:
        """获取技能分页列表：本人独占 + 所有分享（public）的技能"""
        paginator = Paginator(db=self.db, req=req)

        filters = [
            or_(
                Skill.account_id == current_user.id,
                Skill.visibility == "public",
            )
        ]
        if req.search_word:
            filters.append(Skill.name.ilike(f"%{req.search_word}%"))

        stmt = (
            select(Skill)
            .where(*filters)
            .order_by(desc(Skill.created_at))
        )
        skills = await paginator.paginate(stmt)

        return skills, paginator

    async def get_skill(self, skill_id: str, current_user: Account) -> Skill:
        """获取单个技能详情（校验归属/分享权限），入口正文从 DB content 读取"""
        skill = await self._get_visible_skill(skill_id, current_user)
        return skill

    async def get_skill_detail(self, skill_id: str, current_user: Account) -> tuple[Skill, list[dict]]:
        """获取技能详情及本地缓存目录下所有文件"""
        skill = await self._get_visible_skill(skill_id, current_user)

        # 本地缓存缺失/为空时，尝试从 MinIO 归档（archive_url）恢复缓存，避免文件树读不到
        cache_dir = self._cache_dir(skill.id)
        if not cache_dir.exists() or not any(cache_dir.rglob("*")):
            self._restore_cache_from_archive(skill)

        files = []
        if cache_dir.exists():
            for file_path in sorted(cache_dir.rglob("*")):
                if file_path.is_file():
                    relative = str(file_path.relative_to(cache_dir))
                    try:
                        content = file_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        # 二进制文件跳过内容，只返回路径
                        content = None
                    files.append({
                        "path": relative,
                        "content": content,
                        "is_binary": content is None,
                    })

        return skill, files

    def _restore_cache_from_archive(self, skill: Skill) -> None:
        """本地缓存缺失时，从 MinIO 归档 zip 恢复 storage/skills/{skill_id}/。

        缓存可能因清理/跨机器迁移而丢失，归档在 MinIO 仍可下载。恢复失败静默（不影响主流程，
        详情页至少能显示 content 字段兜底）。公共根前缀剥离规则与 upload_zip 一致。
        """
        import requests

        if not skill.archive_url:
            return
        try:
            resp = requests.get(skill.archive_url, timeout=30)
            if resp.status_code != 200:
                return
            cache_dir = self._cache_dir(skill.id)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                all_members = [name for name in zf.namelist() if not name.endswith("/")]
                if not all_members:
                    return
                # 计算公共根前缀（与 upload_zip 一致）：文件共有的最顶层目录
                top_dirs = {p.split("/", 1)[0] for p in all_members if "/" in p}
                common_root = ""
                if len(top_dirs) == 1:
                    only = next(iter(top_dirs))
                    if all(p.startswith(only + "/") for p in all_members if "/" in p):
                        common_root = only + "/"
                cache_dir.mkdir(parents=True, exist_ok=True)
                for member in all_members:
                    relative = member[len(common_root):] if common_root else member
                    if not relative:
                        continue
                    target = cache_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
        except Exception:
            # 恢复失败不影响主流程（content 字段可兜底展示）
            pass

    # ==================== 分享切换 ====================

    async def toggle_visibility(self, skill_id: str, current_user: Account) -> Skill:
        """切换技能可见性：private(独占) <-> public(分享)。仅技能归属者可操作。"""
        skill = await self.db.get(Skill, skill_id)
        if skill is None or skill.account_id != current_user.id:
            raise NotFoundException("技能不存在或无权操作")

        new_visibility = "private" if skill.visibility == "public" else "public"
        await self.update(skill, visibility=new_visibility)
        return skill

    # ==================== 删除 ====================

    async def delete_skill(self, skill_id: str, current_user: Account) -> None:
        """删除技能记录 + 本地缓存 + MinIO 归档。仅技能归属者可操作。"""
        skill = await self.db.get(Skill, skill_id)
        if skill is None or skill.account_id != current_user.id:
            raise NotFoundException("技能不存在或无权操作")

        # 1、删除本地缓存目录
        cache_dir = self._cache_dir(skill.id)
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)

        # 2、删除 MinIO 归档
        if skill.archive_url:
            try:
                self.minio_service.delete_file(skill.archive_url)
            except Exception:
                # 归档删除失败不影响主流程
                pass

        # 3、删除数据库记录
        await self.delete(skill)

    # ==================== 内部工具 ====================

    async def get_skill_zip(self, skill_id: str, current_user: Account):
        """打包本地缓存目录为 zip 供下载，返回 (BytesIO, filename) 元组"""
        import zipfile

        skill = await self._get_visible_skill(skill_id, current_user)

        cache_dir = self._cache_dir(skill.id)
        if not cache_dir.exists():
            raise NotFoundException("技能文件不存在")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in cache_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(cache_dir)
                    zf.write(str(file_path), str(arcname))

        buf.seek(0)

        return buf, f"{skill.name}.zip"

    def get_skill_cache_dir(self, skill: Skill) -> Path:
        """获取技能本地缓存目录（运行期读取技能文件/脚本）"""
        return self._cache_dir(skill.id)

    @staticmethod
    def _cache_dir(skill_id: uuid.UUID | str) -> Path:
        """技能本地缓存目录：storage/skills/{skill_id}/"""
        return SKILL_CACHE_ROOT / str(skill_id)

    async def _get_visible_skill(self, skill_id: str, current_user: Account) -> Skill:
        """校验技能存在且对当前用户可见（归属或分享）"""
        skill = await self.db.get(Skill, skill_id)
        if skill is None:
            raise NotFoundException("技能不存在")
        if skill.account_id != current_user.id and skill.visibility != "public":
            raise NotFoundException("技能不存在或无权访问")
        return skill

    def _archive_bytes(self, data: bytes, filename: str, user_folder: str) -> str:
        """归档原始文件到 MinIO（folder=skills/{user_folder}），失败静默返回空串"""
        try:
            return self.minio_service.upload_file(io.BytesIO(data), filename, folder=f"skills/{user_folder}")
        except Exception:
            return ""

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """解析 Markdown Front Matter（优先 YAML，失败回退简单行解析）"""
        match = FRONTMATTER_RE.match(content)
        if not match:
            raise ValidateException("文件缺少合法的Front Matter（--- ... ---）")

        fm_text = match.group("fm")

        # 1、优先 YAML 解析（支持多行块标量、列表等）
        try:
            import yaml
            meta = yaml.safe_load(fm_text)
            if isinstance(meta, dict):
                return SkillService._extract_name_desc(meta)
        except Exception:
            pass

        # 2、回退：按行解析（兼容值内含冒号等非严格 YAML 写法）
        meta = {}
        for line in fm_text.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            if key.strip():
                meta[key.strip()] = value.strip()

        return SkillService._extract_name_desc(meta)

    @staticmethod
    def _extract_name_desc(meta: dict) -> dict:
        """从解析结果中提取 name/description"""
        name = str(meta.get("name", "")).strip()
        if not name:
            raise ValidateException("FrontMatter中缺少name字段")

        description = str(meta.get("description", "")).strip()
        return {"name": name, "description": description}
