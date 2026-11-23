#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/12/2 18:38
@Author : sunxiaojie
@File   : file_extractor.py
"""
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from langchain_core.documents import Document

from internal.model import UploadFile

logger = logging.getLogger(__name__)

# 复用 unstructured SDK 客户端：langchain-unstructured 每次实例化都会新建 UnstructuredClient（约 700ms），
# 本地模式并不需要连接，共享一个实例即可消除该开销
_unstructured_client = None



@dataclass
class FileExtractor:
    """文件提取提，用于将远程文件、upLoad_fiLe记录加载成LangChain对应的文档或字符串"""

    @staticmethod
    def _get_cos_service():
        """延迟获取 CosService（避免 file_extractor -> cos_service -> service包 循环导入）。

        file_extractor 仅调用 download_file / upload_embedded_image（不触库），
        传 upload_file_service=None 即可，无需创建 session。
        """
        from internal.service.cos_service import CosService
        from internal.service.minio_service import MinioService
        return CosService(upload_file_service=None, minio_service=MinioService())

    def load(
            self,
            upload_file: UploadFile,
            return_text: bool = False,
            is_unstructured: bool = False,
            ocr_provider=None,
            max_pages: int | None = None,
    ) -> list[Document] | str:
        """加载传入的upload_file记录，返回LangChain文档列表或者字符串

        ocr_provider：OCR 提供者（图片/扫描PDF识别）；None 表示不做 OCR
        max_pages：仅对 PDF 生效，限制只处理前 N 页（预览场景避免全量 OCR）
        """
        cos_service = self._get_cos_service()
        # 1、创建一个临时的文件夹
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 2、构建一个临时文件路径（key 可能是 MinIO 完整 URL，需从中解析文件名）
            raw_name = os.path.basename(upload_file.key)
            if "://" in upload_file.key:
                raw_name = os.path.basename(urlparse(upload_file.key).path)
            file_name = unquote(raw_name) or "file"
            file_path = os.path.join(tmp_dir, file_name)
            # 3、将对象存储中的文件下载到本地
            cos_service.download_file(upload_file.key, file_path)
            # 4、从指定的路径中加载文件
            return self.load_from_file(
                file_path, return_text, is_unstructured, ocr_provider, max_pages=max_pages
            )

    @classmethod
    def load_from_url(cls, url: str, return_text: bool = False) -> list[Document] | str:
        """从传入的URL中去加载数据，返回LangChain文档列表或者字符串"""
        # 1、下载远程URL的文件到本地
        response = requests.get(url)
        # 2、将文件下载到本地的临时文件夹
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 3、获取文件的扩展名，并构建临时存储路径，将远程文件存储到本地
            raw_name = os.path.basename(urlparse(url).path)
            file_name = unquote(raw_name) or "file"
            file_path = os.path.join(tmp_dir, file_name)
            with open(file_path, "wb") as file:
                file.write(response.content)

            return cls.load_from_file(file_path, return_text)

    @classmethod
    def _load_text_with_encoding_fallback(cls, file_path: str) -> str:
        """读取文本文件，自动兜底常见编码（utf-8 -> gb18030 -> latin-1），保留原始内容"""
        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @classmethod
    def _load_unstructured(cls, file_path: str) -> list[Document]:
        global _unstructured_client
        from langchain_unstructured import UnstructuredLoader

        if _unstructured_client is None:
            from unstructured_client import UnstructuredClient

            _unstructured_client = UnstructuredClient()
        docs = list(UnstructuredLoader(file_path=file_path, client=_unstructured_client).load())
        if not docs:
            return []
        text = "\n\n".join(d.page_content for d in docs)
        return [Document(page_content=text, metadata={"source": file_path})]

    @classmethod
    def _parse_xlsx_structured(cls, file_path: str) -> str:
        """用纯标准库解析 xlsx 为 Markdown 表格（不依赖 openpyxl）。

        xlsx 本质是 zip：sharedStrings.xml 存字符串，sheet1.xml 存单元格引用。
        """
        import re
        import zipfile
        from xml.etree import ElementTree as ET


        def _local(tag: str) -> str:
            return tag.split("}")[-1] if "}" in tag else tag

        try:
            with zipfile.ZipFile(file_path) as zf:
                # 1、共享字符串表
                shared: list[str] = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in root.iter():
                        if _local(si.tag) == "si":
                            text = "".join(
                                t.text or "" for t in si.iter() if _local(t.tag) == "t"
                            )
                            shared.append(text)
                # 2、找第一个工作表
                sheet_name = None
                for n in zf.namelist():
                    if re.match(r"xl/worksheets/sheet\d+\.xml$", n):
                        sheet_name = n
                        break
                if not sheet_name:
                    return ""
                root = ET.fromstring(zf.read(sheet_name))
                rows: list[list[str]] = []
                for row in root.iter():
                    if _local(row.tag) != "row":
                        continue
                    cells: dict[int, str] = {}
                    for c in row:
                        if _local(c.tag) != "c":
                            continue
                        ref = c.get("r", "")
                        m = re.match(r"([A-Z]+)(\d+)", ref)
                        if not m:
                            continue
                        col = 0
                        for ch in m.group(1):
                            col = col * 26 + (ord(ch) - 64)
                        col -= 1
                        t = c.get("t")
                        v = None
                        for child in c:
                            if _local(child.tag) == "v":
                                v = child.text
                        if t == "s" and v is not None:
                            try:
                                cells[col] = shared[int(v)]
                            except (ValueError, IndexError):
                                cells[col] = v
                        elif v is not None:
                            cells[col] = v
                    if cells:
                        max_col = max(cells.keys())
                        rows.append([cells.get(i, "") for i in range(max_col + 1)])
                if not rows:
                    return ""
                # 3、转 Markdown 表格
                widths = max(len(r) for r in rows)
                lines = []
                for i, row in enumerate(rows):
                    padded = row + [""] * (widths - len(row))
                    lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in padded) + " |")
                    if i == 0:
                        lines.append("| " + " | ".join("---" for _ in padded) + " |")
                return "\n".join(lines)
        except Exception as e:
            logger.warning("xlsx 结构化解析失败: %s", e)
            return ""

    @classmethod
    def _parse_csv_structured(cls, file_path: str) -> str:
        """用标准库 csv 解析为 Markdown 表格（带编码兜底）"""
        import csv
        import io

        content = cls._load_text_with_encoding_fallback(file_path)
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return ""
        lines = []
        for i, row in enumerate(rows):
            lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines)

    @classmethod
    def load_from_file(
            cls,
            file_path: str,
            return_text: bool = False,
            is_unstructured: bool = True,
            ocr_provider=None,
            max_pages: int | None = None,
    ) -> list[Document] | str:
        """从本地文件中加载数据，返回LangChain文档列表或者字符串

        ocr_provider：OCR 提供者（识别图片/扫描版PDF）；不传则跳过 OCR
        """
        # 1、获取文件的扩展名
        delimiter = "\n\n"
        file_extension = Path(file_path).suffix.lower()

        # 2、根据不同的文件扩展名去加载不同的加载器
        if file_extension in [".xlsx", ".xls"]:
            # 结构化表格：转 Markdown 表格（保留列结构），标记 content_type=table
            content = cls._parse_xlsx_structured(file_path)
            if not content:
                # 兜底：走 unstructured 文本提取（langchain-unstructured）
                content = delimiter.join(d.page_content for d in cls._load_unstructured(file_path))
            docs = [Document(page_content=content, metadata={"content_type": "table"})]
            # 内嵌图片：提取 → OCR 识别文字 → 上传保留 URL（image_url）
            try:
                import re as _re
                import zipfile as _zipfile

                with _zipfile.ZipFile(file_path) as zf:
                    media = [
                        (n, zf.read(n)) for n in zf.namelist()
                        if _re.match(r"xl/media/.+\.(png|jpe?g|gif|bmp|webp|tiff?)$", n, _re.IGNORECASE)
                    ]
                cos_service = cls._get_cos_service()
                for name, raw in media:
                    img_path = os.path.join(os.path.dirname(file_path), os.path.basename(name))
                    with open(img_path, "wb") as f:
                        f.write(raw)
                    # OCR 识别图片文字（失败仅告警，不影响图片块生成）
                    img_text = ""
                    if ocr_provider is not None:
                        try:
                            img_text = ocr_provider.recognize_images([img_path]) or ""
                        except Exception as e:
                            logger.warning("xlsx 内嵌图片 OCR 失败 %s: %s", name, e)
                    # 上传到存储后端，保留可访问 URL
                    image_url = ""
                    try:
                        image_url = cos_service.upload_embedded_image(img_path)
                    except Exception as e:
                        logger.warning("xlsx 内嵌图片上传失败 %s: %s", name, e)
                    docs.append(Document(
                        page_content=img_text,
                        metadata={"content_type": "image", "image_url": image_url},
                    ))
            except Exception as e:
                logger.warning("xlsx 内嵌图片提取失败: %s", e)
            return docs if not return_text else content
        elif file_extension in [".docx", ".doc"]:
            docs = cls._load_unstructured(file_path)
            # Word 元数据：标题/页数/页脚（从 docx zip 中提取）
            doc_meta = cls._extract_docx_metadata(file_path)
            if docs and doc_meta:
                docs[0].metadata.setdefault("_doc_meta", {}).update(doc_meta)
            return docs if not return_text else delimiter.join(d.page_content for d in docs)
        elif file_extension in [".pptx", ".ppt"]:
            docs = cls._load_unstructured(file_path)
        elif file_extension == ".pdf":
            # PDF：逐页提取文本（每页一个 Document，metadata 带 page_number 供溯源定位）；
            # 无文本层（扫描件）时用 OCR 逐页识别
            docs = cls._extract_pdf_pages(file_path, ocr_provider=ocr_provider, max_pages=max_pages)
            doc_meta = cls._extract_pdf_metadata(file_path)
            if docs and doc_meta:
                docs[0].metadata["_doc_meta"] = doc_meta
            if return_text:
                return "\n\n".join(d.page_content for d in docs) if docs else ""
            return docs
        elif file_extension in [".md", ".markdown", ".txt"]:
            # 保留原始文本（含 # 标题），供标题感知切分使用；
            # UnstructuredMarkdownLoader 会剥掉 # 导致标题正则匹配不到；
            # txt 常见 GB18030/UTF-8 编码，UnstructuredFileLoader 可能解码失败
            content = cls._load_text_with_encoding_fallback(file_path)
            return [Document(page_content=content)] if not return_text else content
        elif file_extension in [".html", "htm"]:
            docs = cls._load_unstructured(file_path)
        elif file_extension == ".csv":
            # 结构化表格：转 Markdown 表格，标记 content_type=table
            content = cls._parse_csv_structured(file_path)
            doc = Document(page_content=content, metadata={"content_type": "table"})
            return [doc] if not return_text else content
        elif file_extension in [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"]:
            # 图片：OCR 识别文字，保留图片本身 URL（image_url 元数据）
            text = ""
            if ocr_provider is not None:
                text = ocr_provider.recognize_images([file_path])
            doc = Document(
                page_content=text or "",
                metadata={"content_type": "image", "image_url": file_path},
            )
            return [doc] if not return_text else (text or "")
        elif file_extension == ".xml":
            docs = cls._load_unstructured(file_path)
        elif file_extension == ".epub":
            docs = cls._load_unstructured(file_path)
        elif file_extension in [".eml", ".msg"]:
            docs = cls._load_unstructured(file_path)
        else:
            if is_unstructured:
                docs = cls._load_unstructured(file_path)
            else:
                content = cls._load_text_with_encoding_fallback(file_path)
                return [Document(page_content=content)] if not return_text else content

        return delimiter.join(
            [document.page_content for document in docs]) if return_text else docs

    @classmethod
    def _extract_docx_metadata(cls, file_path: str) -> dict:
        """提取 Word 文档元数据：标题/页数/页脚（纯标准库读 docx zip）

        - 标题：docProps/core.xml 的 dc:title
        - 页数：docProps/app.xml 的 Pages
        - 页脚：word/footer*.xml 的文本（拼接去重）
        """
        import zipfile
        from xml.etree import ElementTree as ET

        meta: dict = {"title": "", "page_count": 0, "footer": ""}
        try:
            with zipfile.ZipFile(file_path) as zf:
                names = zf.namelist()

                # 1、标题：core.xml 的 dc:title
                if "docProps/core.xml" in names:
                    root = ET.fromstring(zf.read("docProps/core.xml"))
                    for elem in root.iter():
                        if elem.tag.split("}")[-1] == "title" and elem.text and elem.text.strip():
                            meta["title"] = elem.text.strip()[:255]
                            break

                # 2、页数：app.xml 的 Pages
                if "docProps/app.xml" in names:
                    root = ET.fromstring(zf.read("docProps/app.xml"))
                    for elem in root.iter():
                        if elem.tag.split("}")[-1] == "Pages" and elem.text and elem.text.strip().isdigit():
                            meta["page_count"] = int(elem.text.strip())
                            break

                # 3、页脚：word/footer*.xml 的文本
                footers = []
                for n in sorted(names):
                    if n.startswith("word/footer") and n.endswith(".xml"):
                        try:
                            root = ET.fromstring(zf.read(n))
                            parts = []
                            for elem in root.iter():
                                if elem.tag.split("}")[-1] == "t" and elem.text:
                                    parts.append(elem.text)
                            text = "".join(parts).strip()
                            if text and text not in footers:
                                footers.append(text)
                        except Exception:
                            continue
                if footers:
                    meta["footer"] = " | ".join(footers)[:2000]
        except Exception as e:
            logger.warning("Word 元数据提取失败: %s", e)
        return meta

    @classmethod
    def _extract_pdf_metadata(cls, file_path: str) -> dict:
        """提取 PDF 元数据：标题/页数/页脚

        - 标题：pypdf 的 metadata.title（PDF 内置信息）
        - 页数：reader.pages 数量
        - 页脚：逐页取文本最后一行，统计跨页重复的行（出现 >=2 次视为页脚）
        """
        meta: dict = {"title": "", "page_count": 0, "footer": ""}
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            meta["page_count"] = len(reader.pages)
            if reader.metadata:
                title = (reader.metadata.title or "").strip()
                if title:
                    meta["title"] = title[:255]

            # 页脚：每页最后一行非空文本，去数字/空白归一化后跨页重复 >=2 次视为页脚
            import re as _re

            tail_lines = []
            for page in reader.pages:
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    continue
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if lines:
                    tail_lines.append(lines[-1])
            if len(tail_lines) >= 2:
                from collections import Counter

                # 归一化：去掉数字、空白、标点，用于识别"页码不同的同一页脚"
                def _norm(line: str) -> str:
                    return _re.sub(r"[\d\s\-_|/\\:：.。，,·•\u3000]+", "", line)

                counter = Counter(_norm(line) for line in tail_lines)
                footers = []
                seen_norm = set()
                for line in tail_lines:
                    norm = _norm(line)
                    if counter.get(norm, 0) >= 2 and norm not in seen_norm:
                        seen_norm.add(norm)
                        footers.append(line)
                if footers:
                    meta["footer"] = " | ".join(footers)[:2000]
        except Exception as e:
            logger.warning("PDF 元数据提取失败: %s", e)
        return meta

    @classmethod
    def _extract_pdf_pages(cls, file_path: str, ocr_provider=None, max_pages: int | None = None) -> list:
        """逐页提取 PDF 文本，返回每页一个 Document（metadata 带 page_number，从 1 开始）

        有文本层用 pypdf 逐页提取；扫描件（无文本层）用 OCR 逐页识别。
        每页 Document 的 page_number 用于 segment 溯源定位（内容来自第几页）。
        """
        from langchain_core.documents import Document as LCDocument

        import os as _os
        import tempfile as _tf

        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            page_texts: dict[int, str] = {}
            pending_idx: list[int] = []      # 待 OCR 的页码（保持顺序）
            pending_paths: list[str] = []    # 对应的临时图片路径
            tmp_files: list[str] = []        # 全部临时图片，统一清理
            for idx, page in enumerate(reader.pages[:max_pages], start=1):
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    text = ""
                if not text and ocr_provider is not None:
                    # 扫描页：转图片，收集后统一批量 OCR
                    with _tf.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                        tmp_img = tf.name
                    tmp_files.append(tmp_img)
                    try:
                        if hasattr(page, "images") and page.images:
                            page.images[0].image.save(tmp_img)
                    except Exception:
                        pass
                    if _os.path.exists(tmp_img) and _os.path.getsize(tmp_img) > 0:
                        pending_idx.append(idx)
                        pending_paths.append(tmp_img)
                page_texts[idx] = text
            # 所有扫描页一次性并发 OCR（比逐页调用快数倍），再按页回填
            if pending_paths:
                ocr_texts = ocr_provider.recognize_images_batch(pending_paths)
                for i, idx in enumerate(pending_idx):
                    if i < len(ocr_texts) and ocr_texts[i]:
                        page_texts[idx] = ocr_texts[i]
            return [
                LCDocument(page_content=page_texts.get(i, ""), metadata={"page_number": i})
                for i in range(1, len(page_texts) + 1)
            ]
        except Exception as e:
            logger.warning("PDF 逐页提取失败，回退整页文本: %s", e)
            text = cls._extract_pdf_text(file_path)
            return [LCDocument(page_content=text or "", metadata={"page_number": 0})]
        finally:
            for t in tmp_files:
                try:
                    _os.remove(t)
                except OSError:
                    pass

    @classmethod
    def _extract_pdf_text(cls, file_path: str) -> str:
        """用 pypdf 提取 PDF 文本层"""
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    parts.append("")
            return "\n\n".join(parts)
        except Exception as e:
            logger.warning("PDF 文本提取失败: %s", e)
            return ""

    @classmethod
    def _pdf_to_images(cls, file_path: str) -> list[str]:
        """把 PDF 每页转成图片（供 OCR），返回临时图片路径列表"""
        # 优先 PyMuPDF（fitz）；缺失时尝试 pdf2image；都没有则返回空
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            paths = []
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=200)
                out = os.path.join(os.path.dirname(file_path), f"_page_{i}.png")
                pix.save(out)
                paths.append(out)
            return paths
        except ImportError:
            pass
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(file_path, dpi=200)
            paths = []
            for i, img in enumerate(images):
                out = os.path.join(os.path.dirname(file_path), f"_page_{i}.png")
                img.save(out, "PNG")
                paths.append(out)
            return paths
        except ImportError:
            logger.warning("PDF 转图片需要 PyMuPDF 或 pdf2image，当前均未安装")
            return []
        except Exception as e:
            logger.warning("PDF 转图片失败: %s", e)
            return []
