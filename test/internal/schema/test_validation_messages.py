#!/usr/bin/env python
"""
校验文案契约测试：断言 Pydantic ValidationError 的 message 与旧版 wtforms message 一致。
文案是前端依赖的契约，必须与旧版完全一致。
"""
import pytest
from pydantic import ValidationError

from internal.schema.account_schema import UpdatePasswordReq, UpdateNameReq, UpdateAvatarReq
from internal.schema.ai_schema import GenerateSuggestedQuestionsReq, OptimizePromptReq
from internal.schema.api_key_schema import CreateApiKeyReq
from internal.schema.app_schema import CreateAppReq, DebugChatReq, FallbackHistoryToDraftReq
from internal.schema.audio_schema import AudioToTextReq, MessageToAudioReq
from internal.schema.auth_schema import PasswordLoginReq
from internal.schema.builtin_app_schema import AddBuiltinAppToSpaceReq
from internal.schema.choice_schema import ChoiceReq
from internal.schema.conversation_schema import UpdateConversationNameReq, UpdateMessageFeedbackReq
from internal.schema.dataset_schema import CreateOrUpdateDatasetReq, HitReq
from internal.schema.document_schema import UpdateDocumentNameReq
from internal.schema.oauth_schema import AuthorizeReq
from internal.schema.open_api_schema import OpenAIChatReq
from internal.schema.segment_schema import CreateSegmentReq
from internal.schema.user_memory_schema import GetUserMemoryFactsAtReq, GetUserMemoryFactsWindowReq
from internal.schema.weaviate_vector_schema import WeaviateRecallReq, WeaviateDeleteDocumentReq
from internal.schema.workflow_schema import CreateWorkflowReq


def _extract_first_msg(exc: ValidationError) -> str:
    """提取 ValidationError 中第一个错误的 message"""
    errors = exc.errors()
    if errors:
        return errors[0].get("msg", "")
    return ""


class TestPasswordValidationMessages:
    def test_password_empty(self):
        """密码不能为空"""
        with pytest.raises(ValidationError, match="密码不能为空"):
            UpdatePasswordReq(password="")

    def test_password_pattern(self):
        """密码格式 — regexp message"""
        with pytest.raises(ValidationError, match="密码最少包含一个字母，一个数字，并且长度为8-16"):
            UpdatePasswordReq(password="short")

    def test_password_no_digit(self):
        """密码缺少数字"""
        with pytest.raises(ValidationError, match="密码最少包含一个字母，一个数字，并且长度为8-16"):
            UpdatePasswordReq(password="abcdefgh")

    def test_password_valid(self):
        """合法密码通过"""
        req = UpdatePasswordReq(password="abc12345")
        assert req.password == "abc12345"


class TestNameValidationMessages:
    def test_name_too_long(self):
        """用户名长度超过 25"""
        with pytest.raises(ValidationError, match="用户名称长度在1-25个字符"):
            UpdateNameReq(name="a" * 26)


class TestAvatarValidationMessages:
    def test_avatar_not_url(self):
        """头像必须是 URI"""
        with pytest.raises(ValidationError, match="用户头像必须是uri地址"):
            UpdateAvatarReq(avatar="not-a-url")

    def test_avatar_valid(self):
        req = UpdateAvatarReq(avatar="https://example.com/avatar.png")
        assert req.avatar == "https://example.com/avatar.png"


class TestAppValidationMessages:
    def test_name_empty(self):
        """应用名称不能为空"""
        with pytest.raises(ValidationError, match="应用名称不能为空"):
            CreateAppReq(name="", icon="https://example.com/icon.png")

    def test_name_too_long(self):
        """应用名称最大长度为40字符"""
        with pytest.raises(ValidationError, match="应用名称最大长度为40字符"):
            CreateAppReq(name="a" * 41, icon="https://example.com/icon.png")

    def test_icon_empty(self):
        """应用图标不能为空"""
        with pytest.raises(ValidationError, match="应用图标不能为空"):
            CreateAppReq(name="test", icon="")

    def test_icon_not_url(self):
        """应用图标必须是图片URL链接"""
        with pytest.raises(ValidationError, match="应用图标必须是图片URL链接"):
            CreateAppReq(name="test", icon="not-url")

    def test_app_type_invalid(self):
        """应用类型仅支持 agent 或 orchestrator"""
        with pytest.raises(ValidationError, match="应用类型仅支持 agent 或 orchestrator"):
            CreateAppReq(name="test", icon="https://example.com/icon.png", app_type="bad")


class TestDebugChatValidationMessages:
    def test_query_empty(self):
        """用户提问query不能为空"""
        with pytest.raises(ValidationError, match="用户提问query不能为空"):
            DebugChatReq(query="")

    def test_image_urls_too_many(self):
        """上传的图片数量不能超过5"""
        with pytest.raises(ValidationError, match="上传的图片数量不能超过5"):
            DebugChatReq(query="test", image_urls=["https://example.com/img.png"] * 6)

    def test_image_url_format(self):
        """上传的图片URL地址格式错误"""
        with pytest.raises(ValidationError, match="上传的图片URL地址格式错误"):
            DebugChatReq(query="test", image_urls=["not-a-url"])

    def test_file_ids_too_many(self):
        """上传的附件文件数量不能超过5"""
        with pytest.raises(ValidationError, match="上传的附件文件数量不能超过5"):
            DebugChatReq(query="test", file_ids=["id1", "id2", "id3", "id4", "id5", "id6"])


class TestChoiceValidationMessages:
    def test_choice_and_skip_empty(self):
        """choice 与 skip 至少提供一个"""
        with pytest.raises(ValidationError, match="choice 与 skip 至少提供一个"):
            ChoiceReq(choice="", skip=False, action="")


class TestAuthValidationMessages:
    def test_email_too_short(self):
        """登录邮箱长度在5-25个字符"""
        with pytest.raises(ValidationError, match="登录邮箱长度在5-25个字符"):
            PasswordLoginReq(email="a@b", password="abc12345")

    def test_email_format(self):
        """登录邮箱格式错误"""
        with pytest.raises(ValidationError, match="登录邮箱格式错误"):
            PasswordLoginReq(email="invalid-email", password="abc12345")


class TestConversationValidationMessages:
    def test_name_too_long(self):
        """会话名字长度不能超过100个字符"""
        with pytest.raises(ValidationError, match="会话名字长度不能超过100个字符"):
            UpdateConversationNameReq(name="a" * 101)

    def test_feedback_invalid(self):
        """反馈类型仅支持 like、dislike 或空字符串"""
        with pytest.raises(ValidationError, match="反馈类型仅支持 like、dislike 或空字符串"):
            UpdateMessageFeedbackReq(feedback="invalid")


class TestDatasetValidationMessages:
    def test_name_empty(self):
        """知识库名称不能为空"""
        with pytest.raises(ValidationError, match="知识库名称不能为空"):
            CreateOrUpdateDatasetReq(name="", icon="https://example.com/icon.png")

    def test_icon_not_url(self):
        """知识库图标必须是图片URL地址"""
        with pytest.raises(ValidationError, match="知识库图标必须是图片URL地址"):
            CreateOrUpdateDatasetReq(name="test", icon="bad-url")

    def test_query_empty(self):
        """查询语句不能为空"""
        with pytest.raises(ValidationError, match="查询语句不能为空"):
            HitReq(query="", retrieval_strategy="full_text", k=5)

    def test_retrieval_strategy_invalid(self):
        """检索策略格式错误"""
        with pytest.raises(ValidationError, match="检索策略格式错误"):
            HitReq(query="test", retrieval_strategy="bad", k=5)

    def test_k_out_of_range(self):
        """最大召回数量的范围在1-10"""
        with pytest.raises(ValidationError, match="最大召回数量的范围在1-10"):
            HitReq(query="test", retrieval_strategy="full_text", k=0)


class TestDocumentValidationMessages:
    def test_name_empty(self):
        """文档名称不能为空"""
        with pytest.raises(ValidationError, match="文档名称不能为空"):
            UpdateDocumentNameReq(name="")

    def test_name_too_long(self):
        """文档的名称长度不能超过100"""
        with pytest.raises(ValidationError, match="文档的名称长度不能超过100"):
            UpdateDocumentNameReq(name="a" * 101)


class TestWorkflowValidationMessages:
    def test_name_empty(self):
        """工作流名称不能为空"""
        with pytest.raises(ValidationError, match="工作流名称不能为空"):
            CreateWorkflowReq(name="", tool_call_name="test", icon="https://example.com/icon.png", description="desc")

    def test_tool_call_name_invalid(self):
        """英文名称仅支持字母、数字和下划线"""
        with pytest.raises(ValidationError, match="英文名称仅支持字母、数字和下划线"):
            CreateWorkflowReq(name="test", tool_call_name="123bad", icon="https://example.com/icon.png", description="desc")

    def test_icon_not_url(self):
        """工作流图标必须是图片URL地址"""
        with pytest.raises(ValidationError, match="工作流图标必须是图片URL地址"):
            CreateWorkflowReq(name="test", tool_call_name="test_func", icon="bad", description="desc")

    def test_description_empty(self):
        """工作流描述不能为空"""
        with pytest.raises(ValidationError, match="工作流描述不能为空"):
            CreateWorkflowReq(name="test", tool_call_name="test_func", icon="https://example.com/icon.png", description="")


class TestSegmentValidationMessages:
    def test_content_empty(self):
        """片段内容不能为空"""
        with pytest.raises(ValidationError, match="片段内容不能为空"):
            CreateSegmentReq(content="")

    def test_keywords_not_list(self):
        """关键词列表格式必须为数组 — Pydantic type check"""
        with pytest.raises(ValidationError, match="valid list"):
            CreateSegmentReq(content="test", keywords="not-list")

    def test_keywords_too_many(self):
        """关键词长度范围数量在1-10"""
        with pytest.raises(ValidationError, match="关键词长度范围数量在1-10"):
            CreateSegmentReq(content="test", keywords=["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k10", "k11"])


class TestPaginatorValidationMessages:
    def test_page_size_too_large(self):
        """每页数据的条数范围在1-50"""
        from package.paginator import PaginatorReq
        with pytest.raises(ValidationError, match="每页数据的条数范围在1-50"):
            PaginatorReq(page_size=51)

    def test_current_page_zero(self):
        """每页数据的条数范围在1-9999"""
        from package.paginator import PaginatorReq
        with pytest.raises(ValidationError, match="每页数据的条数范围在1-9999"):
            PaginatorReq(current_page=0)

    def test_defaults(self):
        """默认分页参数"""
        from package.paginator import PaginatorReq
        req = PaginatorReq()
        assert req.current_page == 1
        assert req.page_size == 20


class TestAiValidationMessages:
    def test_message_id_empty(self):
        """消息id不能为空"""
        with pytest.raises(ValidationError, match="消息id不能为空"):
            GenerateSuggestedQuestionsReq(message_id="")

    def test_message_id_format(self):
        """消息id格式必须为uuid"""
        with pytest.raises(ValidationError, match="消息id格式必须为uuid"):
            GenerateSuggestedQuestionsReq(message_id="not-uuid")

    def test_prompt_empty(self):
        """预设prompt不能为空"""
        with pytest.raises(ValidationError, match="预设prompt不能为空"):
            OptimizePromptReq(prompt="")

    def test_prompt_too_long(self):
        """预设prompt的长度不能超过20000个"""
        with pytest.raises(ValidationError, match="预设prompt的长度不能超过20000个"):
            OptimizePromptReq(prompt="a" * 20001)


class TestAudioValidationMessages:
    def test_oss_url_empty(self):
        """OSS URL不能为空"""
        with pytest.raises(ValidationError, match="OSS URL不能为空"):
            AudioToTextReq(ossUrl="")

    def test_message_id_empty(self):
        """消息id不能为空"""
        with pytest.raises(ValidationError, match="消息id不能为空"):
            MessageToAudioReq(message_id="")

    def test_message_id_format(self):
        """消息id格式不正确"""
        with pytest.raises(ValidationError, match="消息id格式不正确"):
            MessageToAudioReq(message_id="not-uuid")


class TestOauthValidationMessages:
    def test_code_empty(self):
        """code代码不能为空"""
        with pytest.raises(ValidationError, match="code代码不能为空"):
            AuthorizeReq(code="")


class TestBuiltinAppValidationMessages:
    def test_builtin_app_id_empty(self):
        """内置应用id不能为空"""
        with pytest.raises(ValidationError, match="内置应用id不能为空"):
            AddBuiltinAppToSpaceReq(builtin_app_id="")

    def test_builtin_app_id_format(self):
        """内置工具id格式必须为UUID"""
        with pytest.raises(ValidationError, match="内置工具id格式必须为UUID"):
            AddBuiltinAppToSpaceReq(builtin_app_id="not-uuid")


class TestOpenApiValidationMessages:
    def test_app_id_empty(self):
        """应用id不能为空"""
        with pytest.raises(ValidationError, match="应用id不能为空"):
            OpenAIChatReq(app_id="", query="test")

    def test_app_id_format(self):
        """应用id格式必须为UUID"""
        with pytest.raises(ValidationError, match="应用id格式必须为UUID"):
            OpenAIChatReq(app_id="not-uuid", query="test")


class TestUserMemoryValidationMessages:
    def test_at_negative(self):
        """时间点at最小值为0"""
        with pytest.raises(ValidationError, match="时间点at最小值为0"):
            GetUserMemoryFactsAtReq(at=-1)

    def test_start_negative(self):
        """窗口开始时间start最小值为0"""
        with pytest.raises(ValidationError, match="窗口开始时间start最小值为0"):
            GetUserMemoryFactsWindowReq(start=-1, end=100)

    def test_end_negative(self):
        """窗口结束时间end最小值为0"""
        with pytest.raises(ValidationError, match="窗口结束时间end最小值为0"):
            GetUserMemoryFactsWindowReq(start=0, end=-1)


class TestApiKeyValidationMessages:
    def test_remark_too_long(self):
        """秘钥备注不能超过100个字符"""
        with pytest.raises(ValidationError, match="秘钥备注不能超过100个字符"):
            CreateApiKeyReq(remark="a" * 101)


class TestWeaviateValidationMessages:
    def test_dataset_id_empty(self):
        """dataset_id不能为空"""
        with pytest.raises(ValidationError, match="dataset_id不能为空"):
            WeaviateRecallReq(dataset_id="", query="test")

    def test_dataset_id_format(self):
        """dataset_id格式错误"""
        with pytest.raises(ValidationError, match="dataset_id格式错误"):
            WeaviateRecallReq(dataset_id="not-uuid", query="test")

    def test_query_empty(self):
        """查询文本不能为空"""
        with pytest.raises(ValidationError, match="查询文本不能为空"):
            WeaviateRecallReq(dataset_id="550e8400-e29b-41d4-a716-446655440000", query="")

    def test_top_k_out_of_range(self):
        """top_k范围1-100"""
        with pytest.raises(ValidationError, match="top_k范围1-100"):
            WeaviateRecallReq(dataset_id="550e8400-e29b-41d4-a716-446655440000", query="test", top_k=0)

    def test_score_threshold_out_of_range(self):
        """score_threshold范围0-1"""
        with pytest.raises(ValidationError, match="score_threshold范围0-1"):
            WeaviateRecallReq(dataset_id="550e8400-e29b-41d4-a716-446655440000", query="test", score_threshold=1.5)

    def test_delete_dataset_id_format(self):
        """WeaviateDeleteDocumentReq dataset_id格式错误"""
        with pytest.raises(ValidationError, match="dataset_id格式错误"):
            WeaviateDeleteDocumentReq(dataset_id="not-uuid")
