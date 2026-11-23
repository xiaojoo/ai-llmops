#!/usr/bin/env python
"""
@Time    : 2026/8/22
@File    : ocr_provider.py

OCR 提供者抽象层：支持本地部署（RapidOCR）与 API（DashScope qwen-vl-ocr 等）两种实现，
通过环境变量 OCR_PROVIDER 切换（local | api），与 embedding_provider 的 local/api 模式一致。

- OCR_PROVIDER=local   -> LocalOcrProvider（RapidOCR ONNX，CPU 推理，需 pip 安装 rapidocr_onnxruntime）
- OCR_PROVIDER=api     -> ApiOcrProvider（DashScope qwen-vl-ocr，需 DASHSCOPE_API_KEY）
"""
import base64
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_OCR_MODEL = "rapidocr"
# DashScope 多模态 OCR 模型
DEFAULT_API_OCR_MODEL = "qwen-vl-ocr"


class OcrProvider(ABC):
    """OCR 提供者抽象：把图片（文件路径或字节）识别为文本"""

    @abstractmethod
    def recognize_image(self, image_path: str) -> str:
        """识别单张图片，返回提取的文本"""
        raise NotImplementedError

    def recognize_images(self, image_paths: list[str]) -> str:
        """识别多张图片，按顺序拼接返回"""
        return "\n\n".join(t for t in self.recognize_images_batch(image_paths) if t)

    def recognize_images_batch(self, image_paths: list[str]) -> list[str]:
        """并发识别多张图片，返回与输入顺序对应的文本列表（PDF 逐页 OCR 用）"""
        if not image_paths:
            return []
        if len(image_paths) == 1:
            try:
                text = self.recognize_image(image_paths[0])
                return [text.strip() if text and text.strip() else ""]
            except Exception as e:
                logger.warning("OCR 识别图片失败 %s: %s", image_paths[0], e)
                return [""]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[int, str] = {}
        # 并发数取 8 与图片数的较小值：IO 密集（HTTP 调用），线程池即可提速
        with ThreadPoolExecutor(max_workers=min(8, len(image_paths))) as pool:
            futures = {pool.submit(self.recognize_image, path): i for i, path in enumerate(image_paths)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    text = fut.result()
                    if text and text.strip():
                        results[idx] = text.strip()
                except Exception as e:
                    logger.warning("OCR 识别图片失败: %s", e)
        return [results.get(i, "") for i in range(len(image_paths))]


class LocalOcrProvider(OcrProvider):
    """本地 RapidOCR 提供者（ONNX 推理，CPU 可跑，数据不出内网）"""

    def __init__(self, **kwargs):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise RuntimeError(
                "本地 OCR 需要安装 rapidocr_onnxruntime（外网不可达时无法安装）；"
                "请改用 OCR_PROVIDER=api 或在内网部署该依赖"
            )
        self._engine = RapidOCR()

    def recognize_image(self, image_path: str) -> str:
        result, _ = self._engine(image_path)
        if not result:
            return ""
        # result 为 [[box, text, score], ...]
        lines = [item[1] for item in result if len(item) >= 2 and item[1]]
        return "\n".join(lines)


class ApiOcrProvider(OcrProvider):
    """DashScope qwen-vl-ocr API 提供者（多模态，支持表格/版面）"""

    def __init__(self, model_name: str = "", api_key: str = "", api_base: str = "", **kwargs):
        import dashscope

        self.model_name = model_name or os.getenv("OCR_API_MODEL", DEFAULT_API_OCR_MODEL)
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.api_base = api_base or os.getenv("DASHSCOPE_API_BASE", "")
        if not self.api_key:
            raise RuntimeError("使用 API OCR 时需配置 DASHSCOPE_API_KEY 环境变量")
        dashscope.api_key = self.api_key
        if self.api_base:
            # dashscope 的 base 要求以 /api/v1 结尾，兼容配置里省略该后缀的写法
            base = self.api_base.rstrip("/")
            dashscope.base_http_api_url = base if base.endswith("/api/v1") else base + "/api/v1"
        self._dashscope = dashscope

    def recognize_image(self, image_path: str) -> str:
        import dashscope

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        # 兼容 base64 前缀（部分模型要求 data URI）
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/jpeg;base64,{image_b64}"},
                    {
                        "text": "请识别图片中的所有文字内容，按阅读顺序输出。使用 Markdown 格式："
                        "标题用 #，段落用纯文本，表格用 Markdown 表格。"
                        "不要输出 HTML 标签（如 <p>、<h2>、<body> 等）。"
                    },
                ],
            }
        ]
        response = dashscope.MultiModalConversation.call(
            model=self.model_name,
            messages=messages,
        )
        if response.status_code != 200:
            raise RuntimeError(f"OCR API 调用失败: {response.code} {response.message}")
        output = response.output
        if not output or not output.get("choices"):
            return ""
        content = output["choices"][0].get("message", {}).get("content", [])
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(parts)
        # 兜底：模型偶尔仍会输出 HTML 标签，剥离后保留文本内容
        if "<" in text and ">" in text:
            import re as _re

            text = _re.sub(r"<[^>]+>", "", text)
            text = text.replace("```html", "").replace("```", "").strip()
        return text


def create_ocr_provider(provider_name: str = "", api_key: str = "", api_base: str = "", model: str = "") -> OcrProvider:
    """根据配置创建对应的 OCR 提供者（local | api | custom）

    优先级：显式参数 > 环境变量 > 默认
    - provider_name: 缺省读 OCR_PROVIDER（默认 api）
    - api_key/api_base/model: custom 模式的自定义配置（缺省读 OCR_API_KEY/OCR_API_BASE/OCR_API_MODEL）
    """
    provider = (provider_name or os.getenv("OCR_PROVIDER", "api")).strip().lower()
    if provider == "local":
        return LocalOcrProvider()
    if provider in ("api", "custom"):
        return ApiOcrProvider(
            model_name=model or os.getenv("OCR_API_MODEL", "") or DEFAULT_API_OCR_MODEL,
            api_key=api_key or os.getenv("OCR_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", ""),
            api_base=api_base or os.getenv("OCR_API_BASE", "") or os.getenv("DASHSCOPE_API_BASE", ""),
        )
    raise RuntimeError(
        f"不支持的 OCR_PROVIDER: {provider}，可选值为 local / api / custom"
    )
