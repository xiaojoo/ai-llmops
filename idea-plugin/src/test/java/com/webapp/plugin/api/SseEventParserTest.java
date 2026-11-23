package com.webapp.plugin.api;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SseEventParserTest {

    @Test
    void errorEventPrefersObservationOverMessage() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse("error",
            "{\"event\":\"error\",\"observation\":\"推理过程发生异常：模型超时\",\"message\":\"fallback\"}");
        assertEquals(SseEventParser.Kind.ERROR, evt.kind());
        assertEquals("推理过程发生异常：模型超时", evt.content(), "应取 observation 里的真实原因");
    }

    @Test
    void errorEventFallsBackToMessageWhenNoObservation() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse("error",
            "{\"event\":\"error\",\"message\":\"认证失败\"}");
        assertEquals(SseEventParser.Kind.ERROR, evt.kind());
        assertEquals("认证失败", evt.content());
    }

    @Test
    void localToolCallEventParsesToKindAndKeepsRawPayload() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse("local_tool_call",
            "{\"task_id\":\"task-1\",\"tool\":\"fs_read\",\"tool_call_id\":\"call_8f91\","
                + "\"tool_input\":{\"path\":\"src/App.vue\"},"
                + "\"conversation_id\":\"c1\",\"message_id\":\"m1\"}");
        assertEquals(SseEventParser.Kind.LOCAL_TOOL_CALL, evt.kind());
        assertEquals("task-1", evt.taskId());
        assertEquals("c1", evt.conversationId());
        assertEquals("m1", evt.messageId());
        assertEquals("fs_read", evt.raw().get("tool").getAsString());
        assertEquals("call_8f91", evt.raw().get("tool_call_id").getAsString());
    }
}
