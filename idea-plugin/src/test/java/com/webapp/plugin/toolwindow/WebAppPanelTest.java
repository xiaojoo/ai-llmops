package com.webapp.plugin.toolwindow;

import com.webapp.plugin.api.SseEventParser;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * WebAppPanel 相关纯逻辑测试。
 * 面板本身依赖 JCEF/IDE 环境（无法单测），这里覆盖其依赖的 SSE 解析语义。
 */
class WebAppPanelTest {

    @Test
    void sseMessageDeltaExtractsContent() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse(
            "agent_message",
            "{\"message\":[{\"content\":\"Hello\"}],\"task_id\":\"t1\"}");
        assertEquals(SseEventParser.Kind.MESSAGE_DELTA, evt.kind());
        assertEquals("Hello", evt.content());
        assertEquals("t1", evt.taskId());
    }

    @Test
    void sseMessageDeltaExtractsAnswerField() {
        // 后端真实结构：回复增量在 answer；message 是完整历史（system/human），不得用作回复
        SseEventParser.ParsedEvent evt = SseEventParser.parse(
            "agent_message",
            "{\"answer\":\"增量文本\",\"message\":[{\"type\":\"system\",\"data\":{\"content\":\"预设\"}}],\"task_id\":\"t2\"}");
        assertEquals(SseEventParser.Kind.MESSAGE_DELTA, evt.kind());
        assertEquals("增量文本", evt.content());
    }

    @Test
    void sseMessageDeltaBlankAnswerNotFallingBackToHistory() {
        // answer 是空白增量（如换行片段）也必须原样返回，不能误取 message 历史
        SseEventParser.ParsedEvent evt = SseEventParser.parse(
            "agent_message",
            "{\"answer\":\"\\n\\n\",\"message\":[{\"type\":\"system\",\"data\":{\"content\":\"这是历史\"}}]}");
        assertEquals("\n\n", evt.content());
    }

    @Test
    void sseEndMarksDone() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse("agent_end", "{}");
        assertEquals(SseEventParser.Kind.END, evt.kind());
    }

    @Test
    void ssePingIgnored() {
        SseEventParser.ParsedEvent evt = SseEventParser.parse("ping", "{}");
        assertEquals(SseEventParser.Kind.IGNORE, evt.kind());
    }
}
