package com.webapp.plugin.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.webapp.plugin.api.WebAppApiClient;
import com.webapp.plugin.util.VoiceRecorder;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BridgeProtocolTest {

    @Test
    void parseActionExtractsAction() {
        assertEquals("openFile",
            WebAppBridge.parseAction("{\"action\":\"openFile\",\"payload\":{\"path\":\"/a/b.java\"}}"));
    }

    @Test
    void parseActionRejectsUnknownShape() {
        assertEquals("", WebAppBridge.parseAction("not-json"));
        assertEquals("", WebAppBridge.parseAction("{\"payload\":{}}"));
        assertEquals("", WebAppBridge.parseAction("{\"action\":123}"));
    }

    @Test
    void buildResponseOk() {
        String resp = WebAppBridge.buildResponse(true, "data", null);
        assertTrue(resp.contains("\"ok\":true"));
        assertTrue(resp.contains("data"));
    }

    @Test
    void buildResponseError() {
        String resp = WebAppBridge.buildResponse(false, null, "boom");
        assertTrue(resp.contains("\"ok\":false"));
        assertTrue(resp.contains("boom"));
    }

    // ===== toChatMessages：历史消息映射 =====
    // 回归：后端消息行字段是 query（用户提问）+ answer（助手回复），无 role/content；
    // 之前错误映射 content/role 导致历史消息全部变成 content="" 的 assistant → 重新进入时空对话。

    private static List<JsonObject> rows(JsonObject... items) {
        return new ArrayList<>(Arrays.asList(items));
    }

    @Test
    void toChatMessagesMapsQueryAndAnswerToUserAndAssistantMessages() {
        JsonObject row = new JsonObject();
        row.addProperty("id", "msg-1");
        row.addProperty("query", "什么是 Agentic RAG？");
        row.addProperty("answer", "Agentic RAG 是把 RAG 交给 Agent 编排……");
        row.addProperty("latency", 3.25);
        row.addProperty("total_token_count", 321);
        row.addProperty("feedback", "like");

        JsonArray arr = WebAppBridge.toChatMessages(rows(row), "conv-1");

        assertEquals(2, arr.size());
        JsonObject user = arr.get(0).getAsJsonObject();
        assertEquals("user", user.get("role").getAsString());
        assertEquals("什么是 Agentic RAG？", user.get("content").getAsString());
        assertEquals("conv-1", user.get("conversationId").getAsString());

        JsonObject assistant = arr.get(1).getAsJsonObject();
        assertEquals("assistant", assistant.get("role").getAsString());
        assertEquals("Agentic RAG 是把 RAG 交给 Agent 编排……", assistant.get("content").getAsString());
        assertEquals("msg-1", assistant.get("messageId").getAsString());
        assertEquals("conv-1", assistant.get("conversationId").getAsString());
        assertEquals(3.25, assistant.get("latency").getAsDouble(), 0.0001);
        assertEquals(321L, assistant.get("totalTokenCount").getAsLong());
        assertEquals("like", assistant.get("feedback").getAsString());
    }

    @Test
    void toChatMessagesReversesNewestFirstRows() {
        // 后端按 created_at 倒序返回（最新在前）；页面按数组顺序渲染（最旧在前），需反转
        // 输入：[m2(最新), m1] → 输出：[m1(最旧), m2]
        List<JsonObject> list = new ArrayList<>();
        for (int i = 2; i >= 1; i--) {
            JsonObject row = new JsonObject();
            row.addProperty("id", "m" + i);
            row.addProperty("query", "q" + i);
            row.addProperty("answer", "a" + i);
            list.add(row);
        }
        JsonArray arr = WebAppBridge.toChatMessages(list, "c");
        assertEquals(4, arr.size());
        assertEquals("user", arr.get(0).getAsJsonObject().get("role").getAsString());
        assertEquals("q1", arr.get(0).getAsJsonObject().get("content").getAsString());
        assertEquals("assistant", arr.get(3).getAsJsonObject().get("role").getAsString());
        assertEquals("a2", arr.get(3).getAsJsonObject().get("content").getAsString());
    }

    @Test
    void toChatMessagesSkipsEmptyQueryOrAnswer() {
        JsonObject onlyAnswer = new JsonObject();
        onlyAnswer.addProperty("id", "x1");
        onlyAnswer.addProperty("query", "");
        onlyAnswer.addProperty("answer", "reply");
        JsonObject onlyQuery = new JsonObject();
        onlyQuery.addProperty("id", "x2");
        onlyQuery.addProperty("query", "ask");
        onlyQuery.addProperty("answer", "");

        JsonArray arr = WebAppBridge.toChatMessages(rows(onlyAnswer, onlyQuery), "c");
        // 反转后：[onlyQuery(→user), onlyAnswer(→assistant)]
        assertEquals(2, arr.size());
        assertEquals("user", arr.get(0).getAsJsonObject().get("role").getAsString());
        assertEquals("ask", arr.get(0).getAsJsonObject().get("content").getAsString());
        assertEquals("assistant", arr.get(1).getAsJsonObject().get("role").getAsString());
        assertEquals("reply", arr.get(1).getAsJsonObject().get("content").getAsString());
    }

    // ===== toChatMessages：历史上传文件回显 =====
    // 回归：后端消息行带 file_urls（[{id, name, size, extension, url}, ...]），
    // 之前映射时被丢弃 → 历史用户消息不显示已上传的附件。

    @Test
    void toChatMessagesCarriesFileUrlsToUserFiles() {
        JsonObject row = new JsonObject();
        row.addProperty("id", "msg-f");
        row.addProperty("query", "分析这份报告");
        row.addProperty("answer", "已分析。");
        JsonArray fileUrls = new JsonArray();
        JsonObject f1 = new JsonObject();
        f1.addProperty("id", "file-1");
        f1.addProperty("name", "报告.pdf");
        f1.addProperty("size", 102400);
        f1.addProperty("extension", "pdf");
        f1.addProperty("url", "https://oss.example/report.pdf");
        JsonObject f2 = new JsonObject();
        f2.addProperty("id", "file-2");
        f2.addProperty("name", "数据.xlsx");
        f2.addProperty("size", 204800);
        f2.addProperty("extension", "xlsx");
        f2.addProperty("url", "https://oss.example/data.xlsx");
        fileUrls.add(f1);
        fileUrls.add(f2);
        row.add("file_urls", fileUrls);

        JsonArray arr = WebAppBridge.toChatMessages(rows(row), "conv-1");

        assertEquals(2, arr.size());
        JsonObject user = arr.get(0).getAsJsonObject();
        assertTrue(user.has("files"), "用户消息应携带 files 字段");
        JsonArray files = user.getAsJsonArray("files");
        assertEquals(2, files.size());
        assertEquals("file-1", files.get(0).getAsJsonObject().get("id").getAsString());
        assertEquals("报告.pdf", files.get(0).getAsJsonObject().get("label").getAsString());
        assertEquals("file-2", files.get(1).getAsJsonObject().get("id").getAsString());
        assertEquals("数据.xlsx", files.get(1).getAsJsonObject().get("label").getAsString());
        // 助手消息不携带 files
        JsonObject assistant = arr.get(1).getAsJsonObject();
        assertTrue(!assistant.has("files"));
    }

    @Test
    void toChatMessagesOmitsFilesWhenFileUrlsEmpty() {
        JsonObject row = new JsonObject();
        row.addProperty("id", "msg-e");
        row.addProperty("query", "无附件");
        row.addProperty("answer", "ok");
        row.add("file_urls", new JsonArray());

        JsonArray arr = WebAppBridge.toChatMessages(rows(row), "c");
        JsonObject user = arr.get(0).getAsJsonObject();
        assertTrue(!user.has("files"), "空 file_urls 不应输出 files 字段");
    }

    // ===== filterProjectFiles：@ 提及项目文件过滤 =====

    @Test
    void filterProjectFilesFiltersCaseInsensitiveAndSorts() {
        List<String> input = Arrays.asList("src/Zeta.java", "README.md", "src/alpha.py", "docs/guide.md");
        List<String> out = WebAppBridge.filterProjectFiles(input, "md", 100);
        assertEquals(Arrays.asList("docs/guide.md", "README.md"), out, "按子串过滤（不区分大小写）后按大小写不敏感排序");
    }

    @Test
    void filterProjectFilesEmptyQueryKeepsAll() {
        List<String> input = Arrays.asList("b.txt", "a.txt", "c.txt");
        List<String> out = WebAppBridge.filterProjectFiles(input, null, 100);
        assertEquals(Arrays.asList("a.txt", "b.txt", "c.txt"), out);
        List<String> out2 = WebAppBridge.filterProjectFiles(input, "  ", 100);
        assertEquals(Arrays.asList("a.txt", "b.txt", "c.txt"), out2, "空白 query 视为不过滤");
    }

    @Test
    void filterProjectFilesTruncatesToMax() {
        List<String> input = Arrays.asList("a.txt", "b.txt", "c.txt", "d.txt");
        List<String> out = WebAppBridge.filterProjectFiles(input, "", 2);
        assertEquals(Arrays.asList("a.txt", "b.txt"), out);
        assertEquals(0, WebAppBridge.filterProjectFiles(input, "zzz", 10).size(), "无匹配返回空");
    }

    // ===== resolveProjectPath：@ 提及项目文件路径安全校验 =====

    @Test
    void resolveProjectPathResolvesFileInsideBase() throws Exception {
        Path base = Files.createTempDirectory("dsh-proj");
        Path src = Files.createDirectories(base.resolve("src"));
        Path file = Files.writeString(src.resolve("main.py"), "print(1)");
        String resolved = WebAppBridge.resolveProjectPath(base.toString(), "src/main.py");
        assertNotNull(resolved);
        assertEquals(file.toRealPath().toString(), resolved);
    }

    @Test
    void resolveProjectPathRejectsTraversalAndAbsolutePaths() throws Exception {
        Path base = Files.createTempDirectory("dsh-proj");
        Path outside = Files.createTempFile("dsh-outside", ".txt");
        assertNull(WebAppBridge.resolveProjectPath(base.toString(), "../" + outside.getFileName()),
            ".. 逃逸应拒绝");
        assertNull(WebAppBridge.resolveProjectPath(base.toString(), outside.toString()), "绝对路径应拒绝");
        assertNull(WebAppBridge.resolveProjectPath(base.toString(), "no-such-file.txt"), "不存在应拒绝");
        assertNull(WebAppBridge.resolveProjectPath(base.toString(), ""), "空白应拒绝");
        assertNull(WebAppBridge.resolveProjectPath(null, "a.txt"), "base 为空应拒绝");
        assertNull(WebAppBridge.resolveProjectPath(base.toString(), "subdir"), "目录应拒绝");
    }

    // ===== buildMultipartBody：上传请求体构造 =====

    @Test
    void buildMultipartBodyContainsBoundaryHeadersAndContent() {
        byte[] body = WebAppApiClient.buildMultipartBody("BOUND123", "报告.pdf", "hello".getBytes(StandardCharsets.UTF_8));
        String s = new String(body, StandardCharsets.UTF_8);
        assertTrue(s.startsWith("--BOUND123\r\n"), "应以 boundary 开头");
        assertTrue(s.contains("Content-Disposition: form-data; name=\"file\"; filename=\"报告.pdf\""), "应含文件名字段");
        assertTrue(s.contains("Content-Type: application/octet-stream"), "应含内容类型");
        assertTrue(s.contains("hello"), "应含文件内容");
        assertTrue(s.endsWith("--BOUND123--\r\n"), "应以 boundary 收尾");
    }

    // ===== VoiceRecorder.buildWav：WAV 头构造 =====

    @Test
    void buildWavWritesValidHeader() {
        byte[] pcm = new byte[1600];
        byte[] wav = VoiceRecorder.buildWav(pcm, 16000f, 16, 1);

        assertEquals("RIFF", new String(wav, 0, 4, StandardCharsets.US_ASCII));
        assertEquals("WAVE", new String(wav, 8, 4, StandardCharsets.US_ASCII));
        assertEquals("fmt ", new String(wav, 12, 4, StandardCharsets.US_ASCII));
        assertEquals("data", new String(wav, 36, 4, StandardCharsets.US_ASCII));
        assertEquals(44 + pcm.length, wav.length, "44 字节头 + PCM 数据");

        // RIFF chunk size = 36 + dataSize（小端）
        int riffSize = (wav[4] & 0xff) | ((wav[5] & 0xff) << 8) | ((wav[6] & 0xff) << 16) | ((wav[7] & 0xff) << 24);
        assertEquals(36 + pcm.length, riffSize);

        // 采样率 16000（小端）
        int rate = (wav[24] & 0xff) | ((wav[25] & 0xff) << 8) | ((wav[26] & 0xff) << 16) | ((wav[27] & 0xff) << 24);
        assertEquals(16000, rate);

        // 单声道 16bit → blockAlign = 2
        int blockAlign = (wav[32] & 0xff) | ((wav[33] & 0xff) << 8);
        assertEquals(2, blockAlign);

        // data chunk size
        int dataSize = (wav[40] & 0xff) | ((wav[41] & 0xff) << 8) | ((wav[42] & 0xff) << 16) | ((wav[43] & 0xff) << 24);
        assertEquals(pcm.length, dataSize);
    }
}
