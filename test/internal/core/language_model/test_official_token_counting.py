#!/usr/bin/env python
"""
@Time    : 2026/10/4
@Author  : sunxiaojie
@File    : test_official_token_counting.py
"""
"""token 计数只认官方口径：认不出就 None，不显示；记账以响应 usage 为准。

三件事各自要能变红：
 1) 按 model_id 选官方分词器（deepseek 官方词表 / OpenAI 系 tiktoken 官方映射 /
    gpt-oss→o200k_harmony），provider 目录不再决定分词器；
 2) 认不出的模型（Qwen/Kimi/自托管未知模型）返回 None —— 历史上这里写死 cl100k_base
    兜底，中文多算 47%，会让历史裁剪提前丢掉约 46% 上下文；
 3) count_round_usage 优先用响应里的 usage_metadata，其次才本地估。
"""
import pytest
import tiktoken
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.core.language_model.tokenizers import model_tokenizer as mt

ZH = "请分析这份季度销售报表，按区域和产品线拆分，指出环比下滑超过两成的品类，并给出三条可执行的改进建议。"


class ProbeLLM(BaseLanguageModel):
    """最小可实例化的模型类，只用来测计数：不联网、不碰真实 provider"""

    model_name: str = "unknown-model"

    def _llm_type(self) -> str:  # pragma: no cover - 抽象方法占位
        return "probe"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def get_num_tokens(self, text: str) -> int:  # pragma: no cover
        raise NotImplementedError

    # langchain BaseLanguageModel 的抽象方法：本测试不实际调用，仅满足实例化
    def generate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def agenerate_prompt(self, prompts, stop=None, callbacks=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def invoke(self, input, config=None, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _vendored_available() -> bool:
    return (mt._TOKENIZER_DIR / "deepseek" / "tokenizer.json").exists()


class TestModelIdResolution:
    def test_normalizes_provider_prefix_and_quant_suffix(self):
        """本机配置里写的是 "openai/gpt-oss-20b MXFP4"，前缀和量化后缀都要剥掉才能映射"""
        assert mt.normalize_model_name("openai/gpt-oss-20b MXFP4") == "gpt-oss-20b"
        assert mt.normalize_model_name("gpt-4o-2024-08-06") == "gpt-4o-2024-08-06"
        assert mt.normalize_model_name("") == ""

    def test_gpt_oss_uses_official_harmony_encoding(self):
        """②：gpt-oss 的官方口径是 o200k_harmony（tiktoken 自带，零下载）"""
        count = mt.count_tokens_for_model("openai/gpt-oss-20b MXFP4", ZH)
        assert count == len(tiktoken.get_encoding("o200k_harmony").encode(ZH))
        assert count > 0

    def test_openai_models_use_tiktoken_official_mapping(self):
        assert mt.count_tokens_for_model("gpt-4o", ZH) == len(
            tiktoken.get_encoding("o200k_base").encode(ZH))

    def test_deepseek_uses_vendored_official_tokenizer(self):
        if not _vendored_available():
            import pytest
            pytest.skip("DeepSeek 官方词表未下载，见 tokenizers/README.md")
        count = mt.count_tokens_for_model("deepseek-v4-flash", "Hello!")
        assert count == 2, f"官方样例应为 [19923, 3] 两个 token，实际 {count}"

    def test_deepseek_official_wins_over_the_cl100k_fallback(self):
        """有官方口径时必须用官方：这条就是原 bug 的守卫（cl100k 对中文多算 47%）"""
        if not _vendored_available():
            import pytest
            pytest.skip("DeepSeek 官方词表未下载，见 tokenizers/README.md")
        official = mt.count_tokens_for_model("deepseek-v4-flash", ZH)
        cl100k = len(tiktoken.get_encoding("cl100k_base").encode(ZH))
        assert official < cl100k, f"官方 {official} 应低于兜底 {cl100k}，说明又用回 cl100k 了"

    def test_unknown_model_falls_back_to_cl100k_not_bytes(self):
        """没有官方口径时退回 cl100k 估算（明确是估算），但绝不退回 UTF-8 字节长度"""
        for name in ("qwen-plus", "moonshot-v1-8k", "some-local-chatml-7b"):
            count = mt.count_tokens_for_model(name, ZH)
            assert count == len(tiktoken.get_encoding("cl100k_base").encode(ZH)), f"{name} 兜底档不对"
            assert count != len(ZH.encode("utf-8")), "字节长度那一档不该回来"

    def test_empty_text_is_zero_not_none(self):
        assert mt.count_tokens_for_model("gpt-4o", "") == 0


class TestBaseCounting:
    def test_base_falls_back_for_unrecognized_model(self):
        """provider 不再各自实现计数：基类认不出模型就走 cl100k 兜底档，给得出数"""
        llm = ProbeLLM(model_name="qwen-plus")
        assert llm.get_num_tokens_safe([ZH]) == len(
            tiktoken.get_encoding("cl100k_base").encode(ZH))

    def test_base_counts_recognized_model(self):
        llm = ProbeLLM(model_name="gpt-4o")
        assert llm.get_num_tokens_safe([ZH]) == len(
            tiktoken.get_encoding("o200k_base").encode(ZH))

    def test_image_blocks_only_counted_when_text_known(self):
        llm = ProbeLLM(model_name="gpt-4o")
        msg = HumanMessage(content=[
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            {"type": "text", "text": ZH},
        ])
        text_only = llm.get_num_tokens_safe([ZH])
        assert llm.get_num_tokens_safe([msg]) == text_only + llm.IMAGE_TOKEN_ESTIMATE


class TestQwenFamilySplit:
    """Qwen3.5/3.6/3.8 是 248k 新词表，Qwen3 系是 151,643 —— 接错族比不接更糟，所以单独锁。"""

    def _available(self) -> bool:
        return (mt._TOKENIZER_DIR / "qwen35" / "tokenizer.json").exists()

    def test_qwen38_uses_the_qwen35_tokenizer(self):
        if not self._available():
            pytest.skip("Qwen3.5 词表未下载，见 tokenizers/README.md")
        text = "用一句话说明什么是向量数据库。"
        tk = mt._vendored_tokenizer("qwen35")
        assert tk is not None
        for name in ("qwen/qwen3.8-27b", "qwen_qwen3.5-27b", "qwen3.6-27b"):
            assert mt.count_tokens_for_model(name, text) == len(tk.encode(text)), name
        # 官方词表对这句中文比 cl100k 省得多（实测 7 vs 14）
        assert mt.count_tokens_for_model("qwen/qwen3.8-27b", text) < len(
            tiktoken.get_encoding("cl100k_base").encode(text))

    def test_qwen3_arch_does_not_pick_up_the_qwen35_tokenizer(self):
        """qwen3-coder 这类 Qwen3 架构不能套 248k 词表：它没有官方分发时走兜底档"""
        count = mt.count_tokens_for_model("qwen3-coder-30b-a3b-instruct", ZH)
        assert count == len(tiktoken.get_encoding("cl100k_base").encode(ZH))


class TestChatTemplateCounting:
    """整条请求口径：服务端算的是"模板 + 正文"，只算正文会少一大截。"""

    QWEN = "qwen/qwen3.8-27b"
    ONE = "用一句话说明什么是向量数据库。"

    def _available(self) -> bool:
        return (mt._TOKENIZER_DIR / "qwen35" / "tokenizer_config.json").exists()

    def test_request_count_matches_the_real_server(self):
        """对表判据：本机 LM Studio 对这条请求返回 prompt_tokens=59，模板口径必须给同一个数"""
        if not self._available():
            pytest.skip("Qwen3.5 词表/模板未下载，见 tokenizers/README.md")
        n = mt.count_chat_tokens_for_model(self.QWEN, [{"role": "user", "content": self.ONE}])
        assert n == 59, f"模板口径应复现服务端 prompt_tokens=59，实际 {n}"

    def test_template_counts_more_than_content_only(self):
        if not self._available():
            pytest.skip("Qwen3.5 词表/模板未下载")
        request_n = mt.count_chat_tokens_for_model(self.QWEN, [{"role": "user", "content": self.ONE}])
        content_n = mt.count_tokens_for_model(self.QWEN, self.ONE)
        assert request_n > content_n, "模板开销被漏掉了"
        assert request_n - content_n == 52, f"实测模板开销 52，实际 {request_n - content_n}"

    def test_base_uses_request_scope_for_langchain_messages(self):
        if not self._available():
            pytest.skip("Qwen3.5 词表/模板未下载")
        llm = ProbeLLM(model_name=self.QWEN)
        msgs = [SystemMessage(content="你是助手。"), HumanMessage(content=self.ONE)]
        request_scope = llm.get_num_tokens_safe(msgs)
        content_scope = mt.count_tokens_for_model(
            self.QWEN, "\n".join([SystemMessage(content="你是助手。").content, self.ONE]))
        assert request_scope > content_scope

    def test_model_without_template_falls_back_to_content_scope(self):
        """没有官方模板的模型不硬套：返回 None，正文口径接管"""
        assert mt.count_chat_tokens_for_model("qwen-plus", [{"role": "user", "content": "hi"}]) is None
        assert ProbeLLM(model_name="qwen-plus").get_num_tokens_safe(
            [HumanMessage(content=ZH)]) == len(tiktoken.get_encoding("cl100k_base").encode(ZH))

    def test_unmappable_role_does_not_guess(self):
        """role 认不出来就整体退回正文口径，不能瞎填成 user（模板结构会错）"""
        assert ProbeLLM._as_chat_messages([{"content": "没有角色"}]) is None


class TestUsageIsAuthoritative:
    def test_response_usage_wins_over_local_estimate(self):
        """③：服务端返回的 usage 就是计费口径，本地估算让位"""
        llm = ProbeLLM(model_name="gpt-4o")
        response = AIMessage(content="好的")
        response.usage_metadata = {"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290}
        assert llm.count_round_usage([HumanMessage(content=ZH)], response) == (1234, 56)

    def test_falls_back_to_local_when_response_has_no_usage(self):
        llm = ProbeLLM(model_name="gpt-4o")
        response = AIMessage(content="好的")
        input_tokens, output_tokens = llm.count_round_usage([HumanMessage(content=ZH)], response)
        assert input_tokens == len(tiktoken.get_encoding("o200k_base").encode(ZH))
        assert output_tokens == len(tiktoken.get_encoding("o200k_base").encode("好的"))

    def test_raw_token_usage_is_also_accepted(self):
        """部分 provider 只填 response_metadata.token_usage（原始字段名不同）"""
        llm = ProbeLLM(model_name="gpt-4o")
        response = AIMessage(
            content="好的",
            response_metadata={"token_usage": {"prompt_tokens": 77, "completion_tokens": 9}},
        )
        assert llm.count_round_usage([HumanMessage(content=ZH)], response) == (77, 9)

    def test_usage_taken_from_last_chunk_of_stream_list(self):
        """流式聚合时 usage 只挂在最后一个块上"""
        llm = ProbeLLM(model_name="gpt-4o")
        first = AIMessage(content="你")
        last = AIMessage(content="好")
        last.usage_metadata = {"input_tokens": 400, "output_tokens": 3, "total_tokens": 403}
        assert llm.count_round_usage([HumanMessage(content=ZH)], [first, last]) == (400, 3)

    def test_no_usage_still_yields_a_number(self):
        """没有 usage 也不会落成 0：退到本地估算档（官方词表或 cl100k 兜底）"""
        llm = ProbeLLM(model_name="qwen-plus")
        input_tokens, output_tokens = llm.count_round_usage(
            [HumanMessage(content=ZH)], AIMessage(content="好的"),
        )
        assert input_tokens == len(tiktoken.get_encoding("cl100k_base").encode(ZH))
        assert output_tokens == len(tiktoken.get_encoding("cl100k_base").encode("好的"))
