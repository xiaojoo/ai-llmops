#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2026/2/26 19:24
@Author  : sunxiaojie
@File    : audio_service.py
"""
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Generator, Union
from urllib import request as urllib_request
from uuid import UUID, uuid4

import dashscope
import requests
from dashscope.audio.asr import Transcription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from .app_service import AppService
from .base_service import BaseService
from internal.config.settings import get_settings
from internal.entity.app_entity import AppStatus
from internal.exception import NotFoundException, FailedException
from internal.model import Account, Message, App, AppConfig, AppConfigVersion, Conversation
from ..entity.conversation_entity import InvokeFrom

logger = logging.getLogger(__name__)


def _cos_public_url(key: str) -> str:
    """构建公网 COS 访问 URL（与 CosService.get_file_url 的 COS 分支一致，绕过 provider 判断）。"""
    cos_domain = os.getenv('COS_DOMAIN')
    if not cos_domain:
        scheme = os.getenv('COS_SCHEME', 'https')
        bucket = os.getenv('COS_BUCKET')
        region = os.getenv('COS_REGION')
        cos_domain = f'{scheme}://{bucket}.cos.{region}.myqcloud.com'
    return f'{cos_domain}/{key}'


def _rehost_to_public_cos(data: bytes, ext: str) -> str:
    """把音频字节上传到公网 COS（audio_stt/ 目录，不建上传记录），返回公网 URL。"""
    from internal.service.cos_service import CosService
    client = CosService.get_client()
    bucket = CosService.get_bucket()
    now = datetime.now()
    upload_key = f"audio_stt/{now.year}/{now.month:02d}/{now.day:02d}/{uuid4().hex}.{ext}"
    client.put_object(bucket, data, upload_key)
    return _cos_public_url(upload_key)


def _resolve_public_audio_url(key: str, cos_base_url: str) -> str:
    """把音频地址解析为 DashScope 公网可访问的 URL。

    - 对象路径（COS 场景）→ cos_base_url + key；
    - 已在公网 COS 域名上 → 直接用；
    - 内网完整 URL（MinIO 场景，key 即 172.20.x.x 等内网地址）→ 下载后转存公网 COS，
      否则阿里云 DashScope 公网取不到音频，识别必然失败。
    """
    if not key:
        return key
    if not (key.startswith("http://") or key.startswith("https://")):
        return cos_base_url + key
    if key.startswith(cos_base_url):
        return key
    try:
        resp = requests.get(key, timeout=30)
        resp.raise_for_status()
        data = resp.content
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else "wav"
        public_url = _rehost_to_public_cos(data, ext)
        logger.info("音频转存公网 COS: %s -> %s", key, public_url)
        return public_url
    except Exception as e:
        logger.warning("音频转存公网 COS 失败，回退原地址 %s: %s", key, e)
        return key


@dataclass
class AudioService(BaseService):
    """语音服务"""
    db: AsyncSession
    app_service: AppService

    async def audio_to_text(self, file_urls, language_hints=None):
        # COS基础地址（系统设置）
        cos_base_url = get_settings().cos_base_url
        # file_urls = ['https://dashscope.oss-cn-beijing.aliyuncs.com/samples/audio/paraformer/hello_world_female2.wav']

        if language_hints is None:
            language_hints = []

        # MinIO 场景 key 是内网完整 URL（阿里云 DashScope 公网取不到）：
        # 先解析成公网可访问地址（对象路径拼 COS 域名；内网地址下载后转存公网 COS）。
        audio_url = await run_in_threadpool(_resolve_public_audio_url, file_urls, cos_base_url)

        # 同步 API 调用，经线程池桥接
        def _do_transcription():
            # 异步提交任务
            task_response = Transcription.async_call(
                model='fun-asr',
                file_urls=[audio_url],
                language_hints=language_hints
            )

            # 等待任务完成
            transcription_response = Transcription.wait(task=task_response.output.task_id)

            if transcription_response.status_code != HTTPStatus.OK:
                raise RuntimeError(f"Transcription API error: {transcription_response.output.message}")

            final_results = []
            for transcription in transcription_response.output['results']:
                if transcription['subtask_status'] == 'SUCCEEDED':
                    url = transcription['transcription_url']
                    result = json.loads(urllib_request.urlopen(url).read().decode('utf8'))
                    final_results.append(result)
                else:
                    final_results.append({"error": "Transcription failed", "details": transcription})

            return final_results

        return await run_in_threadpool(_do_transcription)

    async def message_to_audio(self, message_id: UUID, account: Account) -> Generator:
        """将消息转换成流式时间输出语音"""
        # 1、根据传递的消息id获取消息并校验权限
        message = await self.get(Message, message_id)
        if not message or message.is_deleted or message.answer.strip() == "" or message.created_by != account.id:
            raise NotFoundException("该消息不存在，请核实后重试")

        # 2、校验消息归属的会话状态是否正常
        stmt_conv = select(Conversation).where(Conversation.id == message.conversation_id)
        conversation = (await self.db.execute(stmt_conv)).scalar_one_or_none()
        if conversation is None or conversation.is_deleted or conversation.created_by != account.id:
            raise NotFoundException("该消息会话不存在，请核实后重试")

        enable = True
        voice = "echo"

        invoke_from = str(message.invoke_from)
        if invoke_from in [InvokeFrom.WEB_APP.value, InvokeFrom.DEBUGGER.value]:
            # 3、根据会话信息获取会话归属的应用
            app = await self.get(App, conversation.app_id)
            if app is None:
                raise NotFoundException("该消息会话归属应用不存在或校验失败，请核实后重试")

            # 4、按调用来源分别校验并选取对应配置
            if invoke_from == InvokeFrom.DEBUGGER.value:
                if app.account_id != account.id:
                    raise NotFoundException("该消息会话归属的应用不存在或校验失败，请核实后重试")
                # 查询草稿配置：按 config_type=DRAFT 过滤（version 是整型列）
                from internal.entity.app_entity import AppConfigType
                stmt_draft = select(AppConfigVersion).where(
                    AppConfigVersion.app_id == app.id,
                    AppConfigVersion.config_type == AppConfigType.DRAFT,
                )
                app_config: AppConfig | AppConfigVersion = (await self.db.execute(stmt_draft)).scalar_one_or_none()
            else:
                # 进入本块的只有 WEB_APP / DEBUGGER，此处即 WEB_APP
                if app.status != AppStatus.PUBLISHED.value:
                    raise NotFoundException("该消息会话归属的应用未发布，请核实后重试")
                # 取应用当前指向的发布配置（app.app_config_id）
                if app.app_config_id is None:
                    raise NotFoundException("该应用配置不存在，请核实后重试")
                app_config = await self.get(AppConfig, app.app_config_id)

            # 应用配置可能不存在（app_config_id 为空时为 None）
            if app_config is None:
                raise NotFoundException("该应用配置不存在，请核实后重试")

            text_to_speech = app_config.text_to_speech
            enable = text_to_speech["enable"]
            voice = text_to_speech["voice"]
        elif invoke_from == InvokeFrom.SERVICE_API.value:
            raise NotFoundException("开发API消息不支持文本转语音服务")

        if enable is False:
            raise FailedException("该应用未开启文字转语音功能，请核实后重试")

        text = message.answer.strip()

        # byte_length = len(text.encode("utf-8"))
        # if byte_length > 600:
        #     raise FailedException("文字内容太长，请控制在600字以内（中文约200字）")

        # 5、调用tts服务将消息answer转换成流式事件输出语音
        try:
            dashscope.base_http_api_url = get_settings().dashscope_base_http_api_url
            response = await run_in_threadpool(
                dashscope.MultiModalConversation.call,
                model="qwen3-tts-flash",
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                text=text,
                voice="Cherry",
                format="mp3",
                language_type="Chinese",
                stream=True,
            )

        except Exception:
            logger.exception("文字转语音失败")
            raise FailedException("文字转语音失败，请稍后重试")

        def tts() -> Generator:
            common_data = {
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "audio": "",
            }
            for chunk in response:
                # 处理算法参数错误
                if hasattr(chunk, "code") and chunk.code == "InvalidParameter":
                    msg = str(getattr(chunk, "message", ""))
                    if "Range of input length" in msg:
                        error_data = {**common_data, "error": "文字内容太长，请控制在600字节以内"}
                        yield f"event: tts_error\ndata: {json.dumps(error_data)}\n\n"
                        return
                    if "Voice" in msg:
                        error_data = {**common_data, "error": f"语音 {voice} 不支持，请使用支持的语音"}
                        yield f"event: tts_error\ndata: {json.dumps(error_data)}\n\n"
                        return

                if chunk.output and chunk.output.audio and chunk.output.audio.data:
                    data = {
                        **common_data,
                        "audio": chunk.output.audio.data
                    }
                    yield f"event: tts_message\ndata: {json.dumps(data)}\n\n"
                    if chunk.output.finish_reason == "stop":
                        break
            yield f"event: tts_end\ndata: {json.dumps(common_data)}\n\n"

        return tts()
