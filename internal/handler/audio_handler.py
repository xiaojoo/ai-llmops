#!/usr/bin/env python
"""
@Time    : 2026/2/26 19:20
@author  : sunxiaojie
@File    : audio_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from internal.server.deps import CurrentUser
from internal.schema.audio_schema import AudioToTextReq, MessageToAudioReq
from internal.service import AudioService
from package.response import compact_generate_response, success_json


@dataclass
class AudioHandler:
    """语音处理器"""
    audio_service: AudioService

    async def audio_to_text(self, user: CurrentUser, req: AudioToTextReq) -> None:
        """将语音转换成文本"""
        text = await self.audio_service.audio_to_text(file_urls=req.ossUrl)
        return success_json({"text": text})

    async def message_to_audio(self, user: CurrentUser, req: MessageToAudioReq) -> None:
        """将消息转换成流式输出音频"""
        # audio_service.message_to_audio 是 async def 但内部 return 同步生成器（tts()）——
        # 调用返回的是协程而非 async 生成器，必须 await 解包后再交给 compact_generate_response
        # （StreamingResponse 会在线程池迭代同步生成器）。
        response = await self.audio_service.message_to_audio(UUID(req.message_id), user)
        return compact_generate_response(response)
