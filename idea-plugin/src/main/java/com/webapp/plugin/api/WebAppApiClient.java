package com.webapp.plugin.api;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

/**
 * WebApp 后端 API 客户端（JDK HttpClient，无第三方依赖）。
 *
 * 对接后端 FastAPI：
 * - POST /auth/password_login        → { access_token, expire_at }
 * - GET  /web_apps/{token}           → 应用信息
 * - GET  /web_apps/{token}/conversations?is_pinned=  → 会话列表
 * - GET  /conversations/{id}/messages → 消息历史
 * - POST /web_apps/{token}/chat      → SSE 流式对话
 * - POST /web_apps/{token}/chat/{task_id}/stop → 停止
 *
 * SSE 事件（event: xxx\ndata: {...}）：agent_thought / agent_message / agent_action /
 * ask_user / agent_end / stop / error / timeout / ping
 */
public final class WebAppApiClient {

    private static final Logger LOG = Logger.getLogger(WebAppApiClient.class.getName());

    /** 后端基地址（含端口）。 */
    private final String baseUrl;
    private final HttpClient http;

    public WebAppApiClient(@NotNull String baseUrl) {
        this.baseUrl = trimSlash(baseUrl);
        // 必须显式 HTTP/1.1：JDK HttpClient 默认优先尝试 HTTP/2（h2c），而后端 uvicorn
        // 仅支持 HTTP/1.1——协商失败后请求在 HTTP 层被拒（"Invalid HTTP request received"
        // 或 body 丢失 → "Field required"），导致登录/对话全部失败。
        this.http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(10))
            .build();
    }

    private static String trimSlash(String s) {
        if (s == null) return "";
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        return s;
    }

    // ===== 通用请求 =====

    private HttpRequest.Builder req(String path) {
        return HttpRequest.newBuilder(URI.create(baseUrl + path))
            .timeout(Duration.ofSeconds(30))
            .header("Content-Type", "application/json");
    }

    private HttpRequest.Builder authReq(String path, String token) {
        return req(path).header("Authorization", "Bearer " + token);
    }

    /** 后端鉴权失败（HTTP 200 + {code:"unauthorized"}）异常，供桥接层触发重新登录。 */
    public static class AuthException extends RuntimeException {
        public AuthException(String message) {
            super(message);
        }
    }

    private static boolean isAuthFailure(@Nullable JsonObject json) {
        return json != null && json.has("code") && json.get("code").isJsonPrimitive()
            && "unauthorized".equals(json.get("code").getAsString());
    }

    private static String authFailureMessage(@Nullable JsonObject json) {
        if (json != null && json.has("message") && json.get("message").isJsonPrimitive()) {
            return json.get("message").getAsString();
        }
        return "登录已过期，请重新登录";
    }

    /** 命中鉴权失败 → 抛 AuthException（调用方据此清登录态并提示重新登录）。 */
    private static void rejectIfAuthFailure(@Nullable JsonObject json) {
        if (isAuthFailure(json)) {
            throw new AuthException(authFailureMessage(json));
        }
    }

    // ===== 登录 =====

    /**
     * 账号密码登录。
     *
     * @return 成功：{access_token, expire_at}；
     *         失败：{message: <后端真实错误文案>}（校验失败/凭据错误/其他）；
     *         null：无法解析后端响应
     */
    public @Nullable JsonObject login(@NotNull String email, @NotNull String password) throws IOException, InterruptedException {
        JsonObject body = new JsonObject();
        body.addProperty("email", email);
        body.addProperty("password", password);

        HttpResponse<String> resp = http.send(
            req("/auth/password_login")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                .build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

        JsonObject json = parseObject(resp.body());
        if (resp.statusCode() >= 400 || json == null) {
            return null;
        }
        // 响应结构: { code, message, data }
        // 成功: code=0, data={ access_token, expire_at }
        // 失败: code=fail/validation_error, data={...}（凭据错误/参数校验），message 为真实原因
        JsonElement data = json.get("data");
        if (data != null && data.isJsonObject() && data.getAsJsonObject().has("access_token")) {
            return data.getAsJsonObject();
        }
        // 失败：把后端 message 透传，供上层展示真实原因（而不是笼统的"账号或密码错误"）
        JsonObject failure = new JsonObject();
        if (json.has("message") && json.get("message").isJsonPrimitive()) {
            failure.addProperty("message", json.get("message").getAsString());
        }
        return failure;
    }

    // ===== 应用信息 =====

    public @Nullable JsonObject getWebApp(@NotNull String webAppToken, @NotNull String authToken)
        throws IOException, InterruptedException {
        HttpResponse<String> resp = http.send(
            authReq("/web_apps/" + webAppToken, authToken).GET().build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        if (json == null) return null;
        rejectIfAuthFailure(json);
        JsonElement data = json.get("data");
        return data != null && data.isJsonObject() ? data.getAsJsonObject() : null;
    }

    // ===== 应用列表（多 App 切换） =====

    /**
     * 列出当前账号可用的已发布 WebApp 应用（含 web_app_token），供插件内切换。
     * 对应后端：GET /apps?page_size=50（PaginatorReq 分页上限 50；应用超过 50 个时仅返回第一页）。
     * 仅返回 status == "published" 且有 token 的应用。
     */
    public @NotNull List<JsonObject> listWebApps(@NotNull String authToken)
        throws IOException, InterruptedException {
        List<JsonObject> result = new ArrayList<>();
        HttpResponse<String> resp = http.send(
            authReq("/apps?page_size=50", authToken).GET().build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        if (json == null) return result;
        rejectIfAuthFailure(json);
        JsonElement data = json.get("data");
        // data: { list: [...], paginator: {...} }（PageModel 结构）
        if (data != null && data.isJsonObject()) {
            JsonElement list = data.getAsJsonObject().get("list");
            if (list != null && list.isJsonArray()) {
                for (JsonElement e : list.getAsJsonArray()) {
                    if (!e.isJsonObject()) continue;
                    JsonObject app = e.getAsJsonObject();
                    if (!"published".equals(getString(app, "status"))) continue;
                    String token = getString(app, "token");
                    if (token.isBlank()) continue;
                    JsonObject item = new JsonObject();
                    item.addProperty("token", token);
                    item.addProperty("name", getString(app, "name"));
                    item.addProperty("icon", getString(app, "icon"));
                    result.add(item);
                }
            }
        }
        return result;
    }

    // ===== 插件兜底：确保账号至少有一个已发布的 WebApp =====

    /**
     * 插件兜底：调用 POST /web_apps/plugin/bootstrap。账号下没有已发布应用时后端
     * 自动创建+发布一个默认应用，返回 {@code {token, name, icon, id}}。
     *
     * @param authToken 登录 token
     * @return 后端 data 对象（含 token）；HTTP 失败/响应无 token 返回 null
     */
    public @Nullable JsonObject bootstrapWebApp(@NotNull String authToken)
        throws IOException, InterruptedException {
        HttpResponse<String> resp = http.send(
            authReq("/web_apps/plugin/bootstrap", authToken)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        rejectIfAuthFailure(json);
        if (resp.statusCode() >= 400 || json == null) return null;
        JsonElement data = json.get("data");
        if (data == null || !data.isJsonObject()) return null;
        JsonObject d = data.getAsJsonObject();
        if (!d.has("token") || !d.get("token").isJsonPrimitive()
            || d.get("token").getAsString().isBlank()) {
            return null;
        }
        return d;
    }

    private static String getString(JsonObject o, String key) {
        return o.has(key) && o.get(key).isJsonPrimitive() ? o.get(key).getAsString() : "";
    }

    // ===== 会话列表 =====

    public @NotNull List<JsonObject> listConversations(@NotNull String webAppToken, @NotNull String authToken)
        throws IOException, InterruptedException {
        List<JsonObject> result = new ArrayList<>();
        HttpResponse<String> resp = http.send(
            authReq("/web_apps/" + webAppToken + "/conversations?is_pinned=false", authToken).GET().build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        if (json == null) return result;
        rejectIfAuthFailure(json);
        JsonElement data = json.get("data");
        if (data != null && data.isJsonArray()) {
            for (JsonElement e : data.getAsJsonArray()) {
                if (e.isJsonObject()) result.add(e.getAsJsonObject());
            }
        }
        return result;
    }

    // ===== 消息历史 =====

    public @NotNull List<JsonObject> getMessages(@NotNull String conversationId, @NotNull String authToken)
        throws IOException, InterruptedException {
        List<JsonObject> result = new ArrayList<>();
        HttpResponse<String> resp = http.send(
            authReq("/conversations/" + conversationId + "/messages", authToken).GET().build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        if (json == null) return result;
        rejectIfAuthFailure(json);
        JsonElement data = json.get("data");
        // data 可能是 { list: [...] } 或直接数组
        if (data != null && data.isJsonObject()) {
            JsonElement list = data.getAsJsonObject().get("list");
            if (list != null && list.isJsonArray()) {
                for (JsonElement e : list.getAsJsonArray()) {
                    if (e.isJsonObject()) result.add(e.getAsJsonObject());
                }
            }
        } else if (data != null && data.isJsonArray()) {
            for (JsonElement e : data.getAsJsonArray()) {
                if (e.isJsonObject()) result.add(e.getAsJsonObject());
            }
        }
        return result;
    }

    // ===== 本地文件上传（@ 提及项目文件复用后端上传通道） =====

    /**
     * 把本地文件以 multipart/form-data（字段名 file）上传到后端 /upload-files/file，
     * 与 Web UI 的加号上传同一通道。后端负责大小/类型校验、存储与 FileExtractor 文本抽取。
     *
     * @param authToken 登录 token
     * @param filePath  本地文件绝对路径
     * @return 后端 data 对象（{id, name, size, extension, ...}）；HTTP 失败/响应无 id 返回 null
     */
    public @Nullable JsonObject uploadFile(@NotNull String authToken, @NotNull String filePath)
        throws IOException, InterruptedException {
        Path p = Paths.get(filePath);
        String fileName = p.getFileName() == null ? "file" : p.getFileName().toString();
        byte[] bytes = Files.readAllBytes(p);

        String boundary = "----WebAppBoundary" + Long.toHexString(System.nanoTime());
        byte[] body = buildMultipartBody(boundary, fileName, bytes);

        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + "/upload-files/file"))
            .timeout(Duration.ofSeconds(60))
            .header("Authorization", "Bearer " + authToken)
            .header("Content-Type", "multipart/form-data; boundary=" + boundary)
            .POST(HttpRequest.BodyPublishers.ofByteArray(body))
            .build();

        HttpResponse<String> resp = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        rejectIfAuthFailure(json);
        if (resp.statusCode() >= 400 || json == null) return null;
        JsonElement data = json.get("data");
        if (data == null || !data.isJsonObject()) return null;
        JsonObject d = data.getAsJsonObject();
        if (!d.has("id") || !d.get("id").isJsonPrimitive() || d.get("id").getAsString().isBlank()) {
            return null;
        }
        return d;
    }

    /** 纯逻辑：构造 multipart/form-data 请求体（字段名 file），可单测。 */
    public static byte[] buildMultipartBody(String boundary, String fileName, byte[] content) {
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        String preamble = "--" + boundary + "\r\n"
            + "Content-Disposition: form-data; name=\"file\"; filename=\"" + fileName + "\"\r\n"
            + "Content-Type: application/octet-stream\r\n\r\n";
        try {
            body.write(preamble.getBytes(StandardCharsets.UTF_8));
            body.write(content);
            body.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new IllegalStateException("multipart body 构造失败", e); // ByteArrayOutputStream 不会真实发生
        }
        return body.toByteArray();
    }

    // ===== SSE 流式对话 =====

    /**
     * 发起流式对话（SSE）。
     *
     * @param webAppToken WebApp token
     * @param authToken   登录 token
     * @param conversationId 会话 id（空串则新建）
     * @param query       用户输入
     * @param fileIds     附件文件 id 列表
     * @param mode        对话模式：chat=纯聊天 / agent=智能体（注入工作区文件/命令工具）
     * @param projectRoot Agent 模式的工作区根目录（当前项目根路径，chat 模式可为空）
     * @param localToolRuntime 本地工具运行时：true 时文件工具在插件本地执行
     * @param onEvent     每收到一个 SSE 事件回调（eventName + data）
     * @return taskId（可用于停止）
     */
    public @Nullable String chat(
        @NotNull String webAppToken,
        @NotNull String authToken,
        @NotNull String conversationId,
        @NotNull String query,
        @Nullable List<String> fileIds,
        @NotNull String mode,
        @NotNull String projectRoot,
        boolean localToolRuntime,
        @NotNull Consumer<ChatEvent> onEvent,
        boolean resume,
        @Nullable String resumeMessageId) throws IOException, InterruptedException {

        JsonObject body = new JsonObject();
        body.addProperty("conversation_id", conversationId);
        body.addProperty("query", query);
        body.add("image_urls", new JsonArray());
        JsonArray fileArr = new JsonArray();
        if (fileIds != null) {
            for (String id : fileIds) {
                if (id != null && !id.isBlank()) fileArr.add(id);
            }
        }
        body.add("file_ids", fileArr);
        body.addProperty("resume", resume);
        if (resumeMessageId != null && !resumeMessageId.isBlank()) {
            body.addProperty("resume_message_id", resumeMessageId);
        }
        body.addProperty("mode", mode);
        body.addProperty("project_root", projectRoot);
        body.addProperty("local_tool_runtime", localToolRuntime);

        HttpRequest request = authReq("/web_apps/" + webAppToken + "/chat", authToken)
            .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
            .header("Accept", "text/event-stream")
            .build();

        HttpResponse<InputStream> resp = http.send(request, HttpResponse.BodyHandlers.ofInputStream());
        if (resp.statusCode() >= 400) {
            return null;
        }

        // 后端把鉴权/业务错误返回成 HTTP 200 + JSON（非 SSE）
        String contentType = resp.headers().firstValue("content-type").orElse("");
        if (!contentType.contains("text/event-stream")) {
            JsonObject err = parseObject(new String(resp.body().readAllBytes(), StandardCharsets.UTF_8));
            rejectIfAuthFailure(err);
            // 非鉴权业务错误（如"该WebApp不存在或者未发布"）：透传后端 message，
            // 避免在前端静默变成"未获取到回复"，让用户看到真实原因。
            String msg = err != null && err.has("message") && err.get("message").isJsonPrimitive()
                ? err.get("message").getAsString() : "回复失败";
            throw new IllegalStateException(msg);
        }

        String taskId = null;
        int lastEventId = 0;
        String runId = null;
        BufferedReader reader = new BufferedReader(
            new InputStreamReader(resp.body(), StandardCharsets.UTF_8));
        int reconnectAttempts = 0;
        try {
            while (true) {
                // 读一条 SSE 流；若被硬断，带 Last-Event-ID 重连续传端点补发漏掉的事件。
                try (BufferedReader r = reader) {
                    String eventName = "message";
                    String line;
                    StringBuilder dataBuf = new StringBuilder();
                    while ((line = r.readLine()) != null) {
                        if (line.isEmpty()) {
                            // 事件结束
                            if (dataBuf.length() > 0) {
                                String data = dataBuf.toString();
                                ChatEvent evt = new ChatEvent(eventName, data, lastEventId);
                                if ("agent_message".equals(eventName)) {
                                    // task_id 从事件数据里提取
                                    String tid = extractTaskId(data);
                                    if (tid != null) taskId = tid;
                                    if (runId == null) runId = extractRunId(data);
                                } else if (runId == null) {
                                    runId = extractRunId(data);
                                }
                                onEvent.accept(evt);
                                dataBuf.setLength(0);
                            }
                            eventName = "message";
                            continue;
                        }
                        if (line.startsWith("event:")) {
                            eventName = line.substring(6).trim();
                        } else if (line.startsWith("data:")) {
                            dataBuf.append(line.substring(5).trim());
                        } else if (line.startsWith("id:")) {
                            try { lastEventId = Integer.parseInt(line.substring(3).trim()); }
                            catch (NumberFormatException ignored) { }
                        }
                    }
                    break; // 流正常结束
                } catch (IOException io) {
                    // 连接被硬断：带 Last-Event-ID 重连续传端点，补发丢失的 local_tool_call 等
                    if (runId == null || runId.isBlank() || reconnectAttempts >= 3) throw io;
                    reconnectAttempts++;
                    LOG.info("WebApp chat stream reset, reconnect run=" + runId
                        + " last_event_id=" + lastEventId + " attempt=" + reconnectAttempts);
                    String resumePath = "/web_apps/" + webAppToken + "/chat/" + runId
                        + "/resume?last_event_id=" + lastEventId;
                    HttpResponse<InputStream> r = http.send(
                        authReq(resumePath, authToken).GET()
                            .header("Accept", "text/event-stream").build(),
                        HttpResponse.BodyHandlers.ofInputStream());
                    if (r.statusCode() >= 400) throw io;
                    reader = new BufferedReader(new InputStreamReader(r.body(), StandardCharsets.UTF_8));
                }
            }
        } catch (IOException io) {
            // 重连失败/最终断开：向外抛出，由 WebAppBridge 复位 pending 并提示用户"连接已断开/请重试"
            throw io;
        }
        LOG.info("chatSSE stream ended task=" + taskId + " last_event_id=" + lastEventId
            + " reconnect_attempts=" + reconnectAttempts);
        return taskId;
    }

    /** 从事件数据（data JSON）里提取 run_id（顶层 run 标识，重连续传用）。 */
    private static @Nullable String extractRunId(String json) {
        try {
            JsonElement e = JsonParser.parseString(json);
            if (e.isJsonObject() && e.getAsJsonObject().has("run_id")) {
                return e.getAsJsonObject().get("run_id").getAsString();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /** 从 agent_message 的 JSON 里提取 task_id。 */
    private static @Nullable String extractTaskId(String json) {
        try {
            JsonElement e = JsonParser.parseString(json);
            if (e.isJsonObject() && e.getAsJsonObject().has("task_id")) {
                return e.getAsJsonObject().get("task_id").getAsString();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    // ===== 编辑器代码操作（优化/解释/注释） =====

    /**
     * 编辑器选中代码的 AI 操作（POST /web_apps/{token}/code_action）。
     *
     * @param webAppToken WebApp token
     * @param authToken   登录 token
     * @param action      操作类型：optimize / explain / comment
     * @param code        选中的代码内容
     * @param language    代码语言（编辑器文件类型，如 python / java）
     * @return 成功：{code, explanation}；失败：null
     */
    public @Nullable JsonObject codeAction(
        @NotNull String webAppToken,
        @NotNull String authToken,
        @NotNull String action,
        @NotNull String code,
        @NotNull String language) throws IOException, InterruptedException {

        JsonObject body = new JsonObject();
        body.addProperty("action", action);
        body.addProperty("code", code);
        body.addProperty("language", language);
        HttpRequest request = authReq("/web_apps/" + webAppToken + "/code_action", authToken)
            .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
            .build();
        HttpResponse<String> resp = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() >= 400) {
            return null;
        }
        JsonObject json = parseObject(resp.body());
        rejectIfAuthFailure(json);
        if (json == null) return null;
        if (json.has("data") && json.get("data").isJsonObject()) {
            return json.getAsJsonObject("data");
        }
        return null;
    }

    // ===== 停止 =====

    public void stop(@NotNull String webAppToken, @NotNull String authToken, @NotNull String taskId)
        throws IOException, InterruptedException {
        http.send(
            authReq("/web_apps/" + webAppToken + "/chat/" + taskId + "/stop", authToken)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    // ===== 消息反馈（点赞/点踩） =====

    /**
     * 提交消息反馈。
     *
     * @param conversationId 会话 id
     * @param messageId      消息 id
     * @param feedback       like / dislike / 空串（取消反馈）
     */
    public void feedback(@NotNull String conversationId, @NotNull String messageId,
                         @NotNull String feedback, @NotNull String authToken)
        throws IOException, InterruptedException {
        JsonObject body = new JsonObject();
        body.addProperty("feedback", feedback);
        http.send(
            authReq("/conversations/" + conversationId + "/messages/" + messageId + "/feedback", authToken)
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                .build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    // ===== 本地工具结果回传（Remote Agent + Local Tool Runtime） =====

    /**
     * 把插件本地执行的工具结果回传给后端，供 Agent 解除等待并继续推理。
     * POST /web_apps/{token}/chat/{task_id}/tool-result
     *
     * 失败自动重试（最多 3 次，300/600ms 退避）：本地工具结果一旦丢失，服务器
     * wait_for_tool_result 只能等满 60s 超时，用户侧表现为"莫名中断"，体验极差。
     *
     * @return true=提交成功（2xx）；false=重试后仍未成功。调用方据 false 向用户界面
     *         提示"本地工具结果回传失败/超时，请重试"，避免静默等待 60s。
     */
    public boolean submitToolResult(@NotNull String webAppToken, @NotNull String authToken,
                                    @NotNull String taskId, @NotNull String toolCallId,
                                    @NotNull String result, @NotNull String error) {
        String path = "/web_apps/" + webAppToken + "/chat/" + taskId + "/tool-result";
        JsonObject body = new JsonObject();
        body.addProperty("tool_call_id", toolCallId);
        body.addProperty("result", result == null ? "" : result);
        body.addProperty("error", error == null ? "" : error);
        int attempts = 3;
        Exception lastEx = null;
        for (int i = 1; i <= attempts; i++) {
            String suffix = i > 1 ? " (尝试 " + i + "/" + attempts + ")" : "";
            try {
                LOG.info("submitToolResult -> " + path + " tool_call_id=" + toolCallId
                    + " result_len=" + (result == null ? 0 : result.length())
                    + " error=" + (error == null ? "" : error) + suffix);
                HttpResponse<String> resp = http.send(
                    authReq(path, authToken)
                        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                        .build(),
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (resp.statusCode() < 400) {
                    return true;
                }
                LOG.warning("submitToolResult FAILED status=" + resp.statusCode()
                    + " body=" + resp.body() + " path=" + path + suffix);
                // 4xx（除 408）为不可重试的客户端/校验错误，重试无意义；5xx/超时可重试
                if (resp.statusCode() < 500 && resp.statusCode() != 408) {
                    return false;
                }
                lastEx = new IOException("HTTP " + resp.statusCode());
            } catch (Exception e) {
                lastEx = e;
                LOG.log(Level.WARNING, "submitToolResult EXCEPTION path=" + path + suffix, e);
            }
            if (i < attempts) {
                try {
                    Thread.sleep(300L * i); // 300ms / 600ms 退避
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return false;
                }
            }
        }
        LOG.log(Level.WARNING, "submitToolResult FAILED after " + attempts + " attempts: " + path
            + " tool_call_id=" + toolCallId, lastEx);
        return false;
    }

    // ===== ask_user 选择/计划确认 =====

    /**
     * 提交 ask_user 交互结果（选项选择 / 计划确认执行 / 重新规划 / 跳过）。
     *
     * @param webAppToken WebApp token
     * @param taskId      任务 id（SSE 事件 task_id）
     * @param body        { choice | action+keep_orders, custom, skip, event_id }
     */
    public void choice(@NotNull String webAppToken, @NotNull String taskId,
                       @NotNull JsonObject body, @NotNull String authToken)
        throws IOException, InterruptedException {
        http.send(
            authReq("/web_apps/" + webAppToken + "/chat/" + taskId + "/choice", authToken)
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                .build(),
            HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    // ===== 会话设置（短期记忆轮数） =====

    /**
     * 更新 WebApp 会话的短期记忆窗口轮数（会话级覆盖，按会话独立保存）。
     * 对应后端：POST /web_apps/{token}/conversations/{conversation_id}/settings
     *
     * @param webAppToken   WebApp token
     * @param conversationId 会话 id
     * @param dialogRound   短期记忆轮数（0-100；null = 恢复使用应用默认）
     * @param authToken     登录 token
     * @return 后端 data 对象（更新后的会话，含 dialog_round）；失败返回 null
     */
    public @Nullable JsonObject updateConversationDialogRound(
            @NotNull String webAppToken,
            @NotNull String conversationId,
            @Nullable Integer dialogRound,
            @NotNull String authToken) throws IOException, InterruptedException {
        JsonObject body = new JsonObject();
        if (dialogRound == null) {
            body.add("dialog_round", JsonNull.INSTANCE);
        } else {
            body.addProperty("dialog_round", dialogRound);
        }
        HttpRequest request = authReq(
                "/web_apps/" + webAppToken + "/conversations/" + conversationId + "/settings", authToken)
            .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
            .build();
        HttpResponse<String> resp = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        rejectIfAuthFailure(json);
        if (resp.statusCode() >= 400 || json == null) return null;
        JsonElement data = json.get("data");
        return data != null && data.isJsonObject() ? data.getAsJsonObject() : null;
    }

    // ===== 语音转文字 =====

    /**
     * 语音转文字：传入上传音频得到的 OSS key（/upload-files/file 返回的 data.key），
     * 调 POST /audio/audio_to_text（body {ossUrl: key}），后端拼 cos_base_url 后交给识别服务。
     *
     * @param authToken 登录 token
     * @param ossKey    音频的 MinIO/COS key
     * @return 识别文本；业务失败/HTTP 失败返回 null，成功但无文本返回 ""
     */
    public @Nullable String audioToText(@NotNull String authToken, @NotNull String ossKey)
        throws IOException, InterruptedException {
        JsonObject body = new JsonObject();
        body.addProperty("ossUrl", ossKey);
        HttpRequest request = req("/audio/audio_to_text")
            .header("Authorization", "Bearer " + authToken)
            .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
            .build();
        HttpResponse<String> resp = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonObject json = parseObject(resp.body());
        rejectIfAuthFailure(json);
        if (resp.statusCode() >= 400 || json == null) return null;
        if (json.has("code") && json.get("code").isJsonPrimitive()
            && !"success".equals(json.get("code").getAsString())) {
            return null;
        }
        // 成功结构: { code:"success", data: { text: [ { transcripts: [ { text: "..." } ] } ] } }
        JsonElement data = json.get("data");
        if (data == null || !data.isJsonObject()) return null;
        JsonElement textArr = data.getAsJsonObject().get("text");
        if (textArr != null && textArr.isJsonArray() && textArr.getAsJsonArray().size() > 0) {
            JsonElement first = textArr.getAsJsonArray().get(0);
            if (first.isJsonObject()) {
                JsonElement transcripts = first.getAsJsonObject().get("transcripts");
                if (transcripts != null && transcripts.isJsonArray() && transcripts.getAsJsonArray().size() > 0) {
                    JsonElement t = transcripts.getAsJsonArray().get(0);
                    if (t.isJsonObject()) {
                        JsonElement txt = t.getAsJsonObject().get("text");
                        if (txt != null && txt.isJsonPrimitive()) return txt.getAsString();
                    }
                }
            }
        }
        return "";
    }

    // ===== 工具 =====

    private static @Nullable JsonObject parseObject(String body) {
        if (body == null || body.isBlank()) return null;
        try {
            JsonElement e = JsonParser.parseString(body);
            return e.isJsonObject() ? e.getAsJsonObject() : null;
        } catch (Exception ex) {
            return null;
        }
    }

    /** SSE 事件（eventName + data JSON + 该帧 `id:` 序号，断流定位日志对齐服务端 [sse-write] seq）。 */
    public record ChatEvent(String eventName, String data, int seqId) {
    }

    // ===== 异步封装（供 Bridge 使用，不阻塞 EDT） =====

    public CompletableFuture<@Nullable JsonObject> loginAsync(String email, String password) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                return login(email, password);
            } catch (Exception e) {
                return null;
            }
        });
    }
}
