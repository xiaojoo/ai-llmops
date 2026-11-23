#!/usr/bin/env python
"""PPT 模板引擎：markdown → 模板选页 → 文字填充 → .pptx

移植自 GordenPPTSkill（build_pptx.py）的核心机制，按本仓库主流写法重构：

- run 级文本替换：只改 run 文本，保留模板的位置/大小/字号/字体/颜色；
- 按选中页剪枝（prune）：模板未用页不进入成品；
- 出框检测：仅提示、不阻断保存（对应 GordenPPTSkill 的 max_chars 软参考约定）；
- 内容页超出模板容量时自动复制模板页（part 级克隆，含 rels 重映射），不丢内容；
- 支持任意 .pptx 自定义模板（模式 B）：按占位短语自动识别标题/正文槽，其余文本原样保留。

markdown 约定（工具描述中同步声明）：
    # 标题            → 封面标题（第一行，可选副标题段落跟随其后）
    ## 小节标题       → 一张内容页
    - 要点            → 该页正文槽（无标题时首个要点充当标题槽）
    其它普通文本      → 视为要点
    ---               → 忽略（仅作可读分隔）

填充规则（确定性、无占位符泄漏）：
- 封面页：zh 标题槽 ← 封面标题；en 标题槽 ← 封面标题（仅当含拉丁字母时）；
  副标题槽 ← 副标题；其余可编辑槽清空。
- 内容页：标题槽 ← 小节标题（无标题时取首个要点）；正文槽 ← 要点顺序填充，
  多余要点合并进最后一个正文槽；剩余可编辑槽清空。
- 装饰槽（decorative_slot_ids / editable=false）一律不动。
- 结尾页（模板有 ending 角色时）原样保留（模板自带致谢文案）。
- 合辑型模板（无 cover/ending 角色）：第 1 页充当封面。
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import CONTENT_TYPE as CT
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotMeta:
    """detail.json 中一个文本槽位的元数据。"""

    slot_id: str
    address: dict[str, int]  # {shape_id, paragraph, run?}
    editable: bool = True
    current_text: str = ""
    language: str = ""
    max_chars: int | None = None
    chars_per_line: int | None = None
    max_lines: int | None = None
    autofit: bool = False
    font_size_pt: float | None = None


@dataclass(frozen=True)
class PageMeta:
    """detail.json 中一页（原模板 1 基页码）。"""

    slide_number: int
    role: str
    title_slot_id: str | None
    body_slot_ids: tuple[str, ...]
    decorative_slot_ids: tuple[str, ...]
    slots: tuple[SlotMeta, ...]

    def slot(self, slot_id: str) -> SlotMeta | None:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None


@dataclass(frozen=True)
class TemplateMeta:
    """一套内置模板的元信息（detail.json）。"""

    slug: str
    name: str
    style: str
    page_roles: dict[str, list[int]]  # cover/agenda/section_divider/content/ending
    recommended_pages: list[int]
    pages: dict[int, PageMeta]  # slide_number -> PageMeta


@dataclass
class ContentSlide:
    """markdown 解析出的一张内容页。"""

    title: str
    items: list[str]


@dataclass
class SlidePlan:
    """markdown 解析结果。"""

    deck_title: str
    subtitle: str
    slides: list[ContentSlide]


@dataclass(frozen=True)
class FillEdit:
    """一条填充编辑：原模板页码 + 槽位 + 新文本。"""

    page_number: int
    slot_id: str
    new_text: str


@dataclass
class PageInstance:
    """成品中的一个页面实例：模板页码 + 该实例要应用的编辑。

    同一模板页可被多次实例化（内容页超出模板容量时复制），每次实例的编辑相互独立。
    """

    page_number: int
    edits: list[FillEdit]


# ---------------------------------------------------------------------------
# markdown 解析
# ---------------------------------------------------------------------------


def parse_markdown(markdown: str) -> SlidePlan:
    """把 markdown 解析为 SlidePlan（# → 封面，## → 内容页，- → 要点）。"""
    deck_title = ""
    subtitle = ""
    slides: list[ContentSlide] = []
    cur_title: str | None = None
    cur_items: list[str] = []

    def flush() -> None:
        nonlocal cur_title, cur_items
        if cur_title is not None:
            slides.append(ContentSlide(title=cur_title, items=list(cur_items)))
        cur_title = None
        cur_items = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("# "):
            if not deck_title:
                deck_title = line[2:].strip()
            else:  # 后续 # 视为新内容页
                flush()
                cur_title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            cur_title = line[3:].strip()
        elif line.startswith("- "):
            if cur_title is None:
                continue
            cur_items.append(line[2:].strip())
        else:
            if cur_title is None:
                if deck_title and not subtitle:
                    subtitle = line  # 封面下的第一段普通文本当副标题
                continue
            cur_items.append(line)

    flush()
    return SlidePlan(deck_title=deck_title, subtitle=subtitle, slides=slides)


# ---------------------------------------------------------------------------
# 模板元信息加载
# ---------------------------------------------------------------------------


def list_available_templates() -> list[str]:
    """返回内置模板 slug 列表（按目录名排序）。"""
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in TEMPLATES_DIR.iterdir()
        if d.is_dir() and (d / "template.pptx").exists() and (d / "detail.json").exists()
    )


def load_template_meta(slug: str) -> TemplateMeta | None:
    """加载一套模板的 detail.json；不存在返回 None。"""
    detail_path = TEMPLATES_DIR / slug / "detail.json"
    if not detail_path.exists():
        return None
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("模板 detail.json 解析失败 slug=%s", slug)
        return None

    pages: dict[int, PageMeta] = {}
    for page in data.get("pages", []):
        try:
            slide_number = int(page["slide_number"])
        except (KeyError, TypeError, ValueError):
            continue
        slots = tuple(
            SlotMeta(
                slot_id=s.get("slot_id", ""),
                address={
                    k: int(v)
                    for k, v in (s.get("address") or {}).items()
                    if k in ("shape_id", "paragraph", "run")
                },
                editable=bool(s.get("editable", True)),
                current_text=s.get("current_text") or "",
                language=s.get("language") or "",
                max_chars=s.get("max_chars"),
                chars_per_line=s.get("chars_per_line"),
                max_lines=s.get("max_lines"),
                autofit=bool(s.get("autofit", False)),
                font_size_pt=s.get("font_size_pt"),
            )
            for s in page.get("text_slots", [])
        )
        pages[slide_number] = PageMeta(
            slide_number=slide_number,
            role=page.get("role", "content"),
            title_slot_id=page.get("title_slot_id"),
            body_slot_ids=tuple(page.get("body_slot_ids") or ()),
            decorative_slot_ids=tuple(page.get("decorative_slot_ids") or ()),
            slots=slots,
        )

    if not pages:
        return None
    return TemplateMeta(
        slug=slug,
        name=data.get("name") or slug,
        style=data.get("style") or "",
        page_roles=data.get("page_roles") or {},
        recommended_pages=list(data.get("recommended_pages_for_short_deck") or []),
        pages=pages,
    )


# ---------------------------------------------------------------------------
# 选页
# ---------------------------------------------------------------------------


def select_pages(meta: TemplateMeta) -> tuple[int | None, list[int], int | None]:
    """返回 (封面页, 内容页列表, 结尾页)——均为原模板 1 基页码。

    - 有 cover/ending 角色：直接用；没有（合辑型模板）：第 1 页当封面。
    - 内容页按 recommended_pages_for_short_deck 优先排序（布局更全），其余轮换补充。
    """
    roles = meta.page_roles
    cover = roles.get("cover", [None])[0] if roles.get("cover") else None
    ending = roles.get("ending", [None])[0] if roles.get("ending") else None

    if roles.get("content"):
        content = list(roles["content"])
    else:
        content = sorted(meta.pages.keys())
        if cover in content:
            content.remove(cover)
        if ending in content:
            content.remove(ending)

    # 合辑型模板：第 1 页充当封面
    if cover is None and content:
        cover = content[0]
        content = content[1:]

    if meta.recommended_pages:
        rec = [p for p in meta.recommended_pages if p in content]
        content = rec + [p for p in content if p not in rec]

    return cover, content, ending


# ---------------------------------------------------------------------------
# 填充规划
# ---------------------------------------------------------------------------


def _page_title_slot(page: PageMeta) -> SlotMeta | None:
    """页面的主标题槽：优先 title_slot_id，回退到字号最大的 title 槽。"""
    if page.title_slot_id:
        s = page.slot(page.title_slot_id)
        if s is not None:
            return s
    candidates = [s for s in page.slots if "title" in s.slot_id.lower() and s.editable]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.font_size_pt or 0)


def _body_slots(page: PageMeta) -> list[SlotMeta]:
    """页面的正文槽：优先 body_slot_ids，回退到命名启发式（仅按槽位 id 判断）。"""
    if page.body_slot_ids:
        return [s for s in page.slots if s.slot_id in page.body_slot_ids and s.editable]
    return [
        s
        for s in page.slots
        if s.editable
        and s.slot_id not in page.decorative_slot_ids
        and ("body" in s.slot_id.lower() or "正文" in s.slot_id)
    ]


def _has_latin(text: str) -> bool:
    return any(c.isascii() and c.isalpha() for c in text)


def build_instances(plan: SlidePlan, meta: TemplateMeta) -> tuple[list[PageInstance], list[str]]:
    """根据 SlidePlan 与模板元信息生成页面实例序列 + 出框提示。

    实例顺序即成品页顺序：封面 → 内容页（轮换，超出容量自动复用模板页）→ 结尾页。
    """
    cover_page, content_pages, ending_page = select_pages(meta)
    instances: list[PageInstance] = []
    warnings: list[str] = []

    def push(page_number: int, slot: SlotMeta, text: str, edits: list[FillEdit]) -> None:
        edits.append(FillEdit(page_number=page_number, slot_id=slot.slot_id, new_text=text))
        msg = check_overflow(text, slot)
        if msg:
            warnings.append(f"slide {page_number} {slot.slot_id}: {msg}")

    # ── 封面 ──────────────────────────────────────────────────────────────
    if plan.deck_title and cover_page is not None:
        cover = meta.pages[cover_page]
        edits: list[FillEdit] = []
        title_ids = {
            s.slot_id
            for s in cover.slots
            if s.editable and s.slot_id not in cover.decorative_slot_ids and "title" in s.slot_id.lower()
        }
        if cover.title_slot_id:
            title_ids.add(cover.title_slot_id)
        title_slots = [s for s in cover.slots if s.slot_id in title_ids]
        zh_titles = [s for s in title_slots if s.language == "zh"] or title_slots
        en_titles = [s for s in title_slots if s.language == "en"]
        for s in zh_titles:
            push(cover_page, s, plan.deck_title, edits)
        for s in en_titles:
            push(cover_page, s, plan.deck_title if _has_latin(plan.deck_title) else "", edits)
        for s in cover.slots:
            if not s.editable or s.slot_id in cover.decorative_slot_ids or s.slot_id in title_ids:
                continue
            if "subtitle" in s.slot_id.lower():
                push(cover_page, s, plan.subtitle or "", edits)
            else:
                push(cover_page, s, "", edits)
        instances.append(PageInstance(page_number=cover_page, edits=edits))

    # ── 内容页（轮换模板页，超出容量自动复用并复制） ──────────────────────
    for idx, slide in enumerate(plan.slides):
        page_number = content_pages[idx % len(content_pages)]
        page = meta.pages[page_number]
        edits: list[FillEdit] = []

        title_slot = _page_title_slot(page)
        if not slide.title and slide.items:
            title_text, body_texts = slide.items[0], list(slide.items[1:])
        else:
            title_text, body_texts = slide.title, list(slide.items)

        if title_slot is not None and title_slot.editable:
            push(page_number, title_slot, title_text, edits)

        body_slots = _body_slots(page)
        # 多余要点合并进最后一个正文槽
        if len(body_texts) > len(body_slots) and body_slots:
            head, tail = body_texts[: len(body_slots) - 1], body_texts[len(body_slots) - 1 :]
            body_texts = head + ["\n".join(tail)]
        while len(body_texts) < len(body_slots):
            body_texts.append("")
        for slot, text in zip(body_slots, body_texts):
            push(page_number, slot, text, edits)

        # 其余可编辑槽清空（防占位符泄漏），装饰槽不动
        used_ids = {title_slot.slot_id if title_slot else None, *(s.slot_id for s in body_slots)}
        for s in page.slots:
            if not s.editable or s.slot_id in page.decorative_slot_ids or s.slot_id in used_ids:
                continue
            push(page_number, s, "", edits)

        instances.append(PageInstance(page_number=page_number, edits=edits))

    # ── 结尾页（模板自带致谢文案，原样保留） ──────────────────────────────
    if ending_page is not None:
        instances.append(PageInstance(page_number=ending_page, edits=[]))

    return instances, warnings


# ---------------------------------------------------------------------------
# 出框检测（软提示，不阻断）
# ---------------------------------------------------------------------------


def _visual_width(text: str) -> float:
    """估算文本视觉宽度：中文 1.0 / 空格 0.35 / ASCII 0.5 / 其它 0.8。"""
    width = 0.0
    for c in text:
        if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uff00" <= c <= "\uffef":
            width += 1.0
        elif c == " ":
            width += 0.35
        elif c.isascii():
            width += 0.5
        else:
            width += 0.8
    return width


def check_overflow(text: str, slot: SlotMeta) -> str:
    """返回出框提示；放得下或无法估算返回空串。"""
    if not text or not slot.max_chars or not slot.chars_per_line or not slot.max_lines:
        return ""
    total_vw = _visual_width(text.replace("\n", ""))
    if total_vw <= slot.max_chars:
        return ""
    needed = sum(
        max(1, math.ceil(_visual_width(seg) / slot.chars_per_line))
        for seg in (text.split("\n") or [text])
    )
    msg = (
        f"视觉宽度 {total_vw:.0f} > 容量 {slot.max_chars} "
        f"（约需 {needed} 行 / 可容 {slot.max_lines} 行, {slot.font_size_pt or '?'}pt）"
    )
    if slot.autofit:
        return "AUTOFIT " + msg + " — PowerPoint 会自动缩字"
    return msg


# ---------------------------------------------------------------------------
# 应用编辑（run 级替换，保留格式）
# ---------------------------------------------------------------------------


def _find_shape(shapes, shape_id: int):
    """递归查找 shape（含 group）。"""
    for shape in shapes:
        if shape.shape_id == shape_id:
            return shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            found = _find_shape(shape.shapes, shape_id)
            if found is not None:
                return found
    return None


def _apply_edit(slide, slot: SlotMeta, new_text: str) -> tuple[bool, str]:
    """把文本写入槽位对应 run/段落；返回 (成功, 失败原因)。"""
    address = slot.address
    shape = _find_shape(slide.shapes, address.get("shape_id", -1))
    if shape is None:
        return False, f"shape {address.get('shape_id')} 不存在"
    if not shape.has_text_frame:
        return False, f"shape {address.get('shape_id')} 无文本框"
    tf = shape.text_frame
    paragraph_idx = address.get("paragraph", 0)
    if paragraph_idx >= len(tf.paragraphs):
        return False, f"paragraph {paragraph_idx} 越界"
    para = tf.paragraphs[paragraph_idx]
    runs = list(para.runs)
    if not runs:
        return False, f"paragraph {paragraph_idx} 无 run"
    run_idx = address.get("run")
    if run_idx is None:
        # 段落级：保留 run 0 格式，其余 run 清空
        runs[0].text = new_text
        for r in runs[1:]:
            r.text = ""
    else:
        if run_idx >= len(runs):
            return False, f"run {run_idx} 越界"
        runs[run_idx].text = new_text
    return True, ""


def _remap_r_ids(element, remap: dict[str, str]) -> None:
    """把 XML 中 r: 命名空间的 rId 引用按映射重写（复制幻灯片后 rId 会变化）。"""
    for el in element.iter():
        for attr, value in list(el.attrib.items()):
            if attr.startswith(f"{{{_R_NS}}}") and value in remap:
                el.attrib[attr] = remap[value]


def _duplicate_slide(prs: Presentation, src_part, pristine_element):
    """part 级复制一张幻灯片并注册进 package，返回新 Slide。

    python-pptx 无原生复制 API：克隆源 part 的 XML（用未编辑过的 pristine_element，
    避免把前一个实例的填充内容带进副本），重建关系（rId 自动分配并重映射 XML 引用，
    跳过 notesSlide 防止共享演讲者备注），然后注册 presentation 关系 + sldIdLst。
    """
    package = prs.part.package
    partname = package.next_partname("/ppt/slides/slide%d.xml")
    new_part = src_part.__class__(partname, CT.PML_SLIDE, package, pristine_element)

    remap: dict[str, str] = {}
    for rId, rel in src_part.rels.items():
        if rel.reltype == RT.NOTES_SLIDE:
            continue
        if rel.is_external:
            new_rId = new_part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        else:
            new_rId = new_part.rels.get_or_add(rel.reltype, rel.target_part)
        remap[rId] = new_rId
    _remap_r_ids(new_part._element, remap)

    rId = prs.part.relate_to(new_part, RT.SLIDE)
    prs.slides._sldIdLst.add_sldId(rId)
    return new_part.slide


def _rebuild_sld_id_lst(prs: Presentation, ordered_sld_id_elms) -> None:
    """把 sldIdLst 重排为指定顺序（保留元素实例，避免关系孤儿）。"""
    sld_id_lst = prs.slides._sldIdLst
    for el in list(sld_id_lst):
        sld_id_lst.remove(el)
    for el in ordered_sld_id_elms:
        sld_id_lst.append(el)


# ---------------------------------------------------------------------------
# 自定义 .pptx 模板（GordenPPTSkill 模式 B 的自动化版）
# ---------------------------------------------------------------------------
# 对用户提供的任意 .pptx：按占位短语识别"标题槽/正文槽"，其余文本（数字、图标、
# 页眉等）原样保留；封面取第 1 页，内容页取含占位符的页（轮换 + 超出自动复制）。

_TITLE_PLACEHOLDER_MARKERS = (
    "添加标题",
    "点击此处添加标题",
    "此处输入标题",
    "标题内容",
    "标题文字",
    "你的标题",
    "您的内容打在这里",
)
_BODY_PLACEHOLDER_MARKERS = (
    "单击此处输入",
    "点击此处输入",
    "单击此处添加",
    "点击此处添加",
    "在此处添加详细描述",
    "添加关键字",
    "在此添加关键字",
    "此处输入文字",
    "单击此处添加文本",
    "添加文本",
    "输入你的正文",
    "输入正文",
    "在此框中选择粘贴",
    "选择粘贴",
    "您的标题",
)


def _classify_placeholder(text: str) -> str | None:
    """按占位短语把一段 run 文本归类为 title / body；非占位返回 None。"""
    compact = text.replace("\n", "").replace(" ", "").replace("\u3000", "")
    for marker in _TITLE_PLACEHOLDER_MARKERS:
        if marker in compact:
            return "title"
    for marker in _BODY_PLACEHOLDER_MARKERS:
        if marker in compact:
            return "body"
    return None


def _synth_page(slide_number: int, raw_slots: list[tuple[int, int, int, str, float]]) -> PageMeta:
    """把 (shape_id, paragraph, run, text, font_size) 列表合成为 PageMeta（模式 B）。

    同一文本框内若有占位段落，其余段落视作占位文本的延续（如"在此处添加详细描述文本，
    尽量与标题文本语言风格相符合…"被拆成多段），标记为 clear：填充时一并清空，防止残留。
    """
    # 1) 按 run 分类
    kinds: dict[tuple[int, int, int], str | None] = {}
    for shape_id, paragraph, run, text, _size in raw_slots:
        kinds[(shape_id, paragraph, run)] = _classify_placeholder(text)

    # 2) 同框延续段落 → 'clear'
    by_shape: dict[int, list[tuple[int, int, int]]] = {}
    for key in kinds:
        by_shape.setdefault(key[0], []).append(key)
    for runs in by_shape.values():
        if any(kinds[k] is not None for k in runs):
            for k in runs:
                if kinds[k] is None:
                    kinds[k] = "clear"

    meta_slots: list[SlotMeta] = []
    title_ids: list[str] = []
    body_ids: list[str] = []
    for shape_id, paragraph, run, text, size in raw_slots:
        slot_id = f"s{shape_id}p{paragraph}r{run}"
        kind = kinds.get((shape_id, paragraph, run))
        meta_slots.append(
            SlotMeta(
                slot_id=slot_id,
                address={"shape_id": shape_id, "paragraph": paragraph, "run": run},
                editable=kind is not None,  # 非占位文本不可编辑：原样保留
                current_text=text,
                font_size_pt=size or None,
            )
        )
        if kind == "title":
            title_ids.append(slot_id)
        elif kind == "body":
            body_ids.append(slot_id)
    return PageMeta(
        slide_number=slide_number,
        role="cover" if slide_number == 1 else "content",
        title_slot_id=title_ids[0] if title_ids else None,
        body_slot_ids=tuple(body_ids),
        decorative_slot_ids=(),
        slots=tuple(meta_slots),
    )


def _promote_title(page: PageMeta, slot_id: str) -> PageMeta:
    """把某槽位提升为标题槽（封面无占位标题时，用字号最大的文本槽当标题位）。"""
    new_slots = tuple(
        SlotMeta(
            slot_id=s.slot_id,
            address=s.address,
            editable=s.editable or s.slot_id == slot_id,
            current_text=s.current_text,
            language=s.language,
            max_chars=s.max_chars,
            chars_per_line=s.chars_per_line,
            max_lines=s.max_lines,
            autofit=s.autofit,
            font_size_pt=s.font_size_pt,
        )
        for s in page.slots
    )
    return PageMeta(
        slide_number=page.slide_number,
        role=page.role,
        title_slot_id=slot_id,
        body_slot_ids=page.body_slot_ids,
        decorative_slot_ids=page.decorative_slot_ids,
        slots=new_slots,
    )


def analyze_custom_template(pptx_path: str | os.PathLike) -> list[PageMeta]:
    """解析任意 .pptx，返回逐页 PageMeta（模式 B：占位短语自动识别槽位）。"""
    prs = Presentation(str(pptx_path))
    pages: list[PageMeta] = []

    def walk(shapes, out: list[tuple[int, int, int, str, float]]) -> None:
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(shape.shapes, out)
                continue
            if not shape.has_text_frame:
                continue
            for pi, para in enumerate(shape.text_frame.paragraphs):
                runs = list(para.runs)
                if not runs:
                    continue
                for ri, run in enumerate(runs):
                    text = run.text.strip()
                    if not text:
                        continue
                    size = run.font.size.pt if run.font.size is not None else 0.0
                    out.append((shape.shape_id, pi, ri, text, size))

    for idx, slide in enumerate(prs.slides, 1):
        raw: list[tuple[int, int, int, str, float]] = []
        walk(slide.shapes, raw)
        pages.append(_synth_page(idx, raw))

    # 封面（第 1 页）没有占位标题时：把字号最大的文本槽提升为标题槽
    if pages and pages[0].title_slot_id is None:
        best = max(pages[0].slots, key=lambda s: s.font_size_pt or 0, default=None)
        if best is not None:
            pages[0] = _promote_title(pages[0], best.slot_id)
    return pages


def _looks_like_graphic_page(page: PageMeta) -> bool:
    """图形/数据页检测：图标字符（PUA 区）或数字+单位示例数据占多数的页。

    这类页（如 5k/3k/1k、10K/25K/7K/17K、纯图标页）填充后视觉上仍像"没填内容"，
    自定义模板选内容页时应跳过。注意统计文本必须含数字（避免把占位文案里的
    "，" 单字符误判成数据页）。
    """
    icon_count = 0
    stat_count = 0
    for s in page.slots:
        text = s.current_text.strip()
        if any("\ue000" <= c <= "\uf8ff" for c in text):
            icon_count += 1
        elif re.fullmatch(r"[\d.,]*\d[\d.,]*\s*[KkMm%]?", text):
            stat_count += 1
    return icon_count >= 2 or stat_count >= 2


def build_custom_instances(plan: SlidePlan, pages: list[PageMeta]) -> tuple[list[PageInstance], list[str]]:
    """模式 B 页面实例：封面=第 1 页；内容页=含占位符的页（轮换，超出自动复用）。"""
    pages_by_num = {p.slide_number: p for p in pages}
    cover = pages_by_num.get(1)
    content_pages = [
        p
        for n, p in sorted(pages_by_num.items())
        if n > 1 and p.body_slot_ids and not _looks_like_graphic_page(p)
    ]
    instances: list[PageInstance] = []
    warnings: list[str] = []

    def push(page_number: int, slot: SlotMeta, text: str, edits: list[FillEdit]) -> None:
        edits.append(FillEdit(page_number=page_number, slot_id=slot.slot_id, new_text=text))
        msg = check_overflow(text, slot)
        if msg:
            warnings.append(f"slide {page_number} {slot.slot_id}: {msg}")

    # ── 封面：标题槽 ← 标题；正文槽 ← 副标题或清空；其余占位槽清空 ──
    if plan.deck_title and cover is not None:
        edits: list[FillEdit] = []
        title_slot = _page_title_slot(cover)
        if title_slot is not None:
            push(1, title_slot, plan.deck_title, edits)
        for s in cover.slots:
            if not s.editable or (title_slot is not None and s.slot_id == title_slot.slot_id):
                continue
            if s.slot_id in cover.body_slot_ids:
                push(1, s, plan.subtitle or "", edits)
            else:
                push(1, s, "", edits)
        instances.append(PageInstance(page_number=1, edits=edits))

    # ── 内容页（规则同内置模板） ────────────────────────────────────────
    for idx, slide in enumerate(plan.slides):
        page = content_pages[idx % len(content_pages)]
        edits: list[FillEdit] = []
        title_slot = _page_title_slot(page)
        if not slide.title and slide.items:
            title_text, body_texts = slide.items[0], list(slide.items[1:])
        else:
            title_text, body_texts = slide.title, list(slide.items)
        if title_slot is not None:
            push(page.slide_number, title_slot, title_text, edits)
        body_slots = _body_slots(page)
        if len(body_texts) > len(body_slots) and body_slots:
            head, tail = body_texts[: len(body_slots) - 1], body_texts[len(body_slots) - 1 :]
            body_texts = head + ["\n".join(tail)]
        while len(body_texts) < len(body_slots):
            body_texts.append("")
        for slot, text in zip(body_slots, body_texts):
            push(page.slide_number, slot, text, edits)
        used_ids = {title_slot.slot_id if title_slot else None, *(s.slot_id for s in body_slots)}
        for s in page.slots:
            if not s.editable or s.slot_id in used_ids:
                continue
            push(page.slide_number, s, "", edits)  # 未用的占位槽清空，防占位符泄漏
        instances.append(PageInstance(page_number=page.slide_number, edits=edits))

    return instances, warnings


def _resolve_template_path(ref: str) -> Path | None:
    """把模板引用解析为本地 .pptx 路径。

    依次尝试：绝对路径 → 相对项目根目录 → 项目根目录 templates/ 专属目录。
    """
    p = Path(ref)
    if p.is_file():
        return p
    # 惰性导入：保持工具包模块加载轻量
    from internal.config.settings import get_settings

    root = Path(get_settings().project_root)
    for candidate in (root / ref, root / "templates" / ref):
        if candidate.is_file():
            return candidate
    return None


def _list_root_pptx() -> str:
    """列出项目根目录与 templates/ 专属目录现存的 .pptx 文件名（模板缺失时给排查提示）。"""
    from internal.config.settings import get_settings

    root = Path(get_settings().project_root)
    names: list[str] = []
    for base in (root, root / "templates"):
        try:
            names.extend(p.name for p in base.glob("*.pptx"))
        except OSError:
            continue
    return ", ".join(sorted(set(names)))


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def generate_pptx(
    markdown: str, template_ref: str, output_path: str | os.PathLike
) -> tuple[list[str], str | None]:
    """根据 markdown + 模板（内置 slug 或本地 .pptx 路径）生成 .pptx。

    返回 (warnings, error)：error 非空表示失败（此时不产生输出文件）。
    """
    try:
        plan = parse_markdown(markdown)
        if not plan.deck_title and not plan.slides:
            return [], "markdown 中没有可用的幻灯片内容（至少需要一个 # 标题）"

        meta = load_template_meta(template_ref)
        if meta is not None:
            return _generate_bundled(plan, meta, output_path)

        template_path = _resolve_template_path(template_ref)
        if template_path is None:
            available = ", ".join(list_available_templates()) or "无"
            # 列出项目根目录现存的 .pptx，方便排查（如文件被误删/改名）
            root_pptx = _list_root_pptx()
            hint = f"；项目根目录现存 .pptx：{root_pptx}" if root_pptx else ""
            return [], (
                f"模板 '{template_ref}' 不存在（不是内置模板，也不是项目内的 .pptx 文件）"
                f"{hint}。可选内置模板：{available}"
            )
        return _generate_custom(plan, template_path, output_path)
    except Exception as e:  # 工具兜底：绝不把异常泄漏给 Agent
        logger.exception("模板生成 PPT 失败 template=%s", template_ref)
        return [], f"生成PPT演示文稿失败，错误原因: {e!s}"


def _generate_bundled(
    plan: SlidePlan, meta: TemplateMeta, output_path: str | os.PathLike
) -> tuple[list[str], str | None]:
    """内置模板路径：detail.json 槽位填充 + 剪枝。"""
    instances, warnings = build_instances(plan, meta)
    if not instances:
        return [], "没有生成任何页面"
    template_path = TEMPLATES_DIR / meta.slug / "template.pptx"
    prs = Presentation(str(template_path))
    return _render_instances(prs, meta.pages, instances, warnings, output_path)


def _generate_custom(
    plan: SlidePlan, template_path: Path, output_path: str | os.PathLike
) -> tuple[list[str], str | None]:
    """自定义 .pptx 路径：模式 B 占位符自动识别 + 填充 + 剪枝。"""
    pages = analyze_custom_template(template_path)
    if not pages:
        return [], f"模板文件 '{template_path}' 没有可解析的页面"
    instances, warnings = build_custom_instances(plan, pages)
    if not instances:
        return [], "没有生成任何页面（模板没有可填充的内容页）"
    prs = Presentation(str(template_path))
    page_metas = {p.slide_number: p for p in pages}
    return _render_instances(prs, page_metas, instances, warnings, output_path)


def _render_instances(
    prs: Presentation,
    page_metas: dict[int, PageMeta],
    instances: list[PageInstance],
    warnings: list[str],
    output_path: str | os.PathLike,
) -> tuple[list[str], str | None]:
    """应用编辑（首次出现用原模板页，重复出现用 part 级复制）、重排并保存。"""
    pristine: dict[int, Any] = {
        p: copy.deepcopy(prs.slides[p - 1].part._element) for p in page_metas
    }
    orig_sld_id_lst = list(prs.slides._sldIdLst.sldId_lst)

    seen: set[int] = set()
    ordered_sld_id_elms: list[Any] = []
    apply_failures = 0
    for inst in instances:
        page_number = inst.page_number
        if page_number in seen:
            src_part = prs.slides[page_number - 1].part
            dup = _duplicate_slide(prs, src_part, copy.deepcopy(pristine[page_number]))
            sld_id_elm = prs.slides._sldIdLst.sldId_lst[-1]
            slide = dup
        else:
            seen.add(page_number)
            sld_id_elm = orig_sld_id_lst[page_number - 1]
            slide = prs.slides[page_number - 1]

        page_meta = page_metas[page_number]
        for edit in inst.edits:
            slot = page_meta.slot(edit.slot_id)
            if slot is None:
                continue
            ok, reason = _apply_edit(slide, slot, edit.new_text)
            if not ok:
                apply_failures += 1
                warnings.append(f"slide {page_number} {edit.slot_id}: {reason}")
        ordered_sld_id_elms.append(sld_id_elm)

    _rebuild_sld_id_lst(prs, ordered_sld_id_elms)
    prs.save(str(output_path))

    if apply_failures:
        warnings.append(f"有 {apply_failures} 处槽位未成功替换，请检查模板与内容")
    return warnings, None
