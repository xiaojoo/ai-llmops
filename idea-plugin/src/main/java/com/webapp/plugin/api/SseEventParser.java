package com.webapp.plugin.api;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

/**
 * SSE 事件语义解析：把后端原始事件转换成 UI 渲染所需的统一结构。
 * 纯逻辑类，便于单元测试。
 */
public final class SseEventParser {

    /** 事件类型（对 UI 有意义的部分）。 */
    public enum Kind {
        /** 推理/工具调用过程 */
        THOUGHT,
        /** AI 回复增量文本 */
        MESSAGE_DELTA,
        /** 本轮结束 */
        END,
        /** 需要用户选择 */
        ASK_USER,
        /** 本地工具运行时：插件本地执行文件工具 */
        LOCAL_TOOL_CALL,
        /** 错误 */
        ERROR,
        /** 忽略（ping 等） */
        IGNORE,
    }

    /** 解析后的事件。 */
    public record ParsedEvent(Kind kind, String content, @Nullable String taskId,
                              @Nullable JsonObject raw, @Nullable String conversationId,
                              @Nullable String messageId, @Nullable String runId) {
        /** 兼容旧 4 参构造（测试用）。 */
        public ParsedEvent(Kind kind, String content, @Nullable String taskId,
                           @Nullable JsonObject raw) {
            this(kind, content, taskId, raw, null, null, null);
        }
    }

    private SseEventParser() {
    }

    /**
     * 解析一个原始 SSE 事件。
     *
     * @param eventName SSE event 名（agent_message / agent_thought / ...）
     * @param data      SSE data JSON 字符串
     */
    public static @NotNull ParsedEvent parse(@NotNull String eventName, @NotNull String data) {
        JsonObject obj = tryParseObject(data);
        String taskId = obj != null ? getString(obj, "task_id") : null;
        String conversationId = obj != null ? getString(obj, "conversation_id") : null;
        String messageId = obj != null ? getString(obj, "message_id") : null;
        String runId = obj != null ? getString(obj, "run_id") : null;

        switch (eventName) {
            case "agent_message": {
                // 增量文本在 message 数组或 llm_output 里
                String content = extractMessageContent(obj);
                return new ParsedEvent(Kind.MESSAGE_DELTA, content, taskId, obj, conversationId, messageId, runId);
            }
            case "agent_thought": {
                String text = getString(obj, "thought");
                if (text == null || text.isBlank()) {
                    text = getString(obj, "llm_output");
                }
                return new ParsedEvent(Kind.THOUGHT, text == null ? "" : text, taskId, obj, conversationId, messageId, runId);
            }
            case "agent_end":
                return new ParsedEvent(Kind.END, "", taskId, obj, conversationId, messageId, runId);
            case "ask_user": {
                String question = getString(obj, "question");
                return new ParsedEvent(Kind.ASK_USER, question == null ? "" : question, taskId, obj, conversationId, messageId, runId);
            }
            case "local_tool_call": {
                // 本地工具运行时：把原始 payload 交给 bridge 解析执行（tool/tool_input/tool_call_id/task_id）
                return new ParsedEvent(Kind.LOCAL_TOOL_CALL, "", taskId, obj, conversationId, messageId, runId);
            }
            case "error": {
                // 后端 error 事件把原因放在 observation（如 "推理过程发生异常：xxx"），
                // 部分场景用 message；优先取 observation，避免前端只显示笼统兜底文案。
                String text = getString(obj, "observation");
                if (text == null || text.isBlank()) {
                    text = getString(obj, "message");
                }
                return new ParsedEvent(Kind.ERROR, text == null ? "" : text, taskId, obj, conversationId, messageId, runId);
            }
            case "stop":
            case "timeout":
                return new ParsedEvent(Kind.END, "", taskId, obj, conversationId, messageId, runId);
            case "ping":
            default:
                return new ParsedEvent(Kind.IGNORE, "", taskId, obj, conversationId, messageId, runId);
        }
    }

    /** 从 agent_message 数据中提取增量文本。 */
    private static String extractMessageContent(@Nullable JsonObject obj) {
        if (obj == null) return "";
        // 后端真实结构：助手回复的增量在 answer 字段（逐事件累加拼接即完整回复）；
        // message 数组是完整会话历史（system 预设 + human 提问），不能作为回复文本。
        // 注意：answer 即使为空白（如 "\n\n"）也是有效增量，必须原样返回，
        // 否则会误落到 message 分支把整段历史当成回复渲染。
        if (obj.has("answer") && obj.get("answer").isJsonPrimitive()) {
            return obj.get("answer").getAsString();
        }
        // 兼容旧结构: { message: [{ content: "..." }] } / { message: [{ data: { content } }] }
        //           / { message: "..." } / { llm_output: "..." }
        JsonElement msg = obj.get("message");
        if (msg != null && msg.isJsonArray()) {
            StringBuilder sb = new StringBuilder();
            for (JsonElement e : msg.getAsJsonArray()) {
                if (e.isJsonObject()) {
                    JsonObject item = e.getAsJsonObject();
                    JsonElement content = item.get("content");
                    if (content != null && content.isJsonPrimitive()) {
                        sb.append(content.getAsString());
                        continue;
                    }
                    // 嵌套结构: { type, data: { content } }
                    JsonElement data = item.get("data");
                    if (data != null && data.isJsonObject()) {
                        JsonElement nested = data.getAsJsonObject().get("content");
                        if (nested != null && nested.isJsonPrimitive()) {
                            sb.append(nested.getAsString());
                        }
                    }
                } else if (e.isJsonPrimitive()) {
                    sb.append(e.getAsString());
                }
            }
            return sb.toString();
        }
        if (msg != null && msg.isJsonPrimitive()) {
            return msg.getAsString();
        }
        String out = getString(obj, "llm_output");
        return out == null ? "" : out;
    }

    private static @Nullable JsonObject tryParseObject(String data) {
        if (data == null || data.isBlank()) return null;
        try {
            JsonElement e = JsonParser.parseString(data);
            return e.isJsonObject() ? e.getAsJsonObject() : null;
        } catch (Exception ex) {
            return null;
        }
    }

    private static @Nullable String getString(JsonObject obj, String key) {
        if (obj == null) return null;
        JsonElement e = obj.get(key);
        if (e != null && e.isJsonPrimitive()) {
            return e.getAsString();
        }
        return null;
    }
}
