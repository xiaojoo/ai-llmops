package com.webapp.plugin.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.intellij.openapi.Disposable;
import com.intellij.openapi.application.Application;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.project.ProjectManager;
import com.intellij.openapi.vfs.LocalFileSystem;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.ui.jcef.JBCefBrowser;
import com.intellij.ui.jcef.JBCefBrowserBase;
import com.intellij.ui.jcef.JBCefJSQuery;
import com.webapp.plugin.api.SseEventParser;
import com.webapp.plugin.api.WebAppApiClient;
import com.webapp.plugin.api.LocalToolRuntime;
import com.webapp.plugin.settings.WebAppSettingsState;
import com.webapp.plugin.util.VoiceRecorder;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

/**
 * WebApp 页面 → IDE 桥（JS→Java）。
 * 保留 IDE 集成能力（openFile / getCurrentFile / refresh）。
 * 新增聊天 API（新架构：插件自建聊天 UI 直连后端）：
 *   login / authStatus / getWebApp / listSessions / loadMessages / send / stop
 * SSE 事件经 executeJavaScript 推回页面 window.__agentChatEvent。
 */
public final class WebAppBridge implements Disposable {

    private static final Logger LOG = Logger.getInstance(WebAppBridge.class);

    private static final Set<String> DECLARED_NOT_IMPLEMENTED = Set.of("openDirectory", "getProjectRoot");

    /** @ 提及项目文件：返回给前端的最大条数 */
    private static final int MAX_MENTION_FILES = 2000;
    /** @ 提及项目文件：目录遍历访问条目上限（防止超大仓库卡住调用线程） */
    private static final int MAX_SCAN_ENTRIES = 50000;
    /** @ 提及项目文件：目录遍历最大深度 */
    private static final int MAX_SCAN_DEPTH = 15;
    /** @ 提及项目文件：跳过的高噪音目录（node_modules/build/缓存等） */
    private static final Set<String> SKIP_DIR_NAMES = Set.of(
        ".git", ".idea", ".gradle", "node_modules", "build", "out", "dist", "target",
        "venv", ".venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
        ".next", ".nuxt", "coverage");
    /** @ 提及项目文件：单文件上传大小上限（10MB，防止超大文件塞满请求体） */
    private static final long MAX_PROJECT_FILE_BYTES = 10L * 1024 * 1024;
    /** @ 提及项目文件：后端 file_ids 上限（含手动上传的附件） */
    private static final int MAX_TOTAL_FILE_IDS = 5;

    private final JBCefBrowser browser;
    private final Project project;
    private final java.util.function.Function<String, JBCefJSQuery.Response> handler = this::handle;
    private JBCefJSQuery jsQuery;
    private final WebAppApiClient api;
    /** ask_user 等待用户选择期间置位：60s 超时保护对交互等待场景放行 */
    private final java.util.concurrent.atomic.AtomicBoolean askUserPending = new java.util.concurrent.atomic.AtomicBoolean(false);
    /** 本地工具运行时等待插件执行期间置位：60s 超时保护对"等本地工具结果"场景放行 */
    private final java.util.concurrent.atomic.AtomicBoolean localToolPending = new java.util.concurrent.atomic.AtomicBoolean(false);
    /** 最近收到 SSE 事件的时间戳：超时改为"空闲超时"，只要有事件（含 ping）就重置 */
    private volatile long lastActivityAt = System.currentTimeMillis();
    /** 本地工具运行时：当前选中工作区根目录（handleSend 写入，供 SSE 线程的 local_tool_call 使用） */
    private volatile String currentProjectRoot = "";
    /** 语音输入：javax.sound 采集麦克风（JCEF 不支持 getUserMedia 的替代） */
    private final VoiceRecorder voiceRecorder = new VoiceRecorder();
    /**
     * 本地工具执行器（单线程串行）：把 fs_* 的执行 + 结果回传放到独立线程，
     * 不阻塞 SSE 消费线程。SSE 线程只负责快速派发，否则 handleLocalToolCall 里的
     * 文件 I/O + HTTP 回传一旦卡住，会让 SSE 读取停滞、后续事件堆积/连接被断，
     * 表现为"某个 local_tool_call 丢失 → 服务器 wait_for_tool_result 只能超时"。
     *
     * 配套看门狗 localToolWatchdog：单个工具的"执行 + 结果回传"若在
     * LOCAL_TOOL_WATCHDOG_TIMEOUT_MS 内仍未完成（本地文件 I/O 卡死 / HTTP 回传黑洞），
     * 由看门狗线程尽力 POST 一次超时错误——服务器提前解除等待，且单线程 worker
     * 不再被一个卡死任务串行拖住、把后续所有本地工具都带超时。
     */
    /** 本地工具"执行+回传"看门狗阈值（ms）：须小于服务器 LOCAL_TOOL_WAIT_TIMEOUT(60s)，让看门狗先到先报 */
    private static final long LOCAL_TOOL_WATCHDOG_TIMEOUT_MS = 40_000L;
    private final java.util.concurrent.ExecutorService localToolExecutor =
        java.util.concurrent.Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "webapp-local-tool");
            t.setDaemon(true);
            return t;
        });
    /** 本地工具看门狗：单工具超时未回传时尽力上报超时错误（独立于 SSE，杜绝静默丢结果） */
    private final java.util.concurrent.ScheduledExecutorService localToolWatchdog =
        java.util.concurrent.Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "webapp-local-tool-watchdog");
            t.setDaemon(true);
            return t;
        });

    public WebAppBridge(@NotNull JBCefBrowser browser, @NotNull Project project) {
        this.browser = browser;
        this.project = project;
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        this.api = new WebAppApiClient(settings.backendUrl);
        // 用 JBCefBrowserBase 重载：JBCefJSQuery.create(JBCefBrowser) 已标记 forRemoval 弃用，
        // 官方替代入口是 create(JBCefBrowserBase)（JBCefBrowser 是其子类，直接传入即可）
        this.jsQuery = JBCefJSQuery.create((JBCefBrowserBase) browser);
        this.jsQuery.addHandler(handler);
    }

    /**
     * 页面加载完成后调用：把 JBCefJSQuery 的函数名暴露为 window.agentChatHost，
     * 供 Web UI 调用（JS → Java）。
     */
    public void installJsBridge() {
        if (jsQuery == null || browser == null || browser.getCefBrowser() == null) return;
        String funcName = jsQuery.getFuncName();
        String js = "window.agentChatHost = window." + funcName + ";"
            + "console.log('[AgentChat] bridge installed: " + funcName + "');";
        browser.getCefBrowser().executeJavaScript(js, browser.getCefBrowser().getURL(), 0);
    }

    /** 纯逻辑：解析 JS 传来的 JSON，提取 action；畸形/未知返回空串。 */
    public static String parseAction(String json) {        if (json == null || json.isBlank()) {
            return "";
        }
        try {
            com.google.gson.JsonObject obj =
                com.google.gson.JsonParser.parseString(json).getAsJsonObject();
            if (!obj.has("action") || !obj.get("action").isJsonPrimitive()
                || !obj.get("action").getAsJsonPrimitive().isString()) {
                return "";
            }
            return obj.get("action").getAsString();
        } catch (Exception e) {
            return "";
        }
    }

    /** 纯逻辑：构造响应 JSON。 */
    public static String buildResponse(boolean ok, Object data, String error) {
        StringBuilder sb = new StringBuilder("{\"ok\":").append(ok);
        if (data != null) {
            sb.append(",\"data\":").append(toJson(data));
        }
        if (error != null) {
            sb.append(",\"error\":").append(toJson(error));
        }
        sb.append("}");
        return sb.toString();
    }

    /** 字符串转 JSON 字面量：转义引号、反斜杠、换行/回车/制表符及控制字符。 */
    private static String toJson(Object o) {
        if (o instanceof String s) {
            StringBuilder sb = new StringBuilder("\"");
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '\\' -> sb.append("\\\\");
                    case '"' -> sb.append("\\\"");
                    case '\n' -> sb.append("\\n");
                    case '\r' -> sb.append("\\r");
                    case '\t' -> sb.append("\\t");
                    default -> {
                        if (c < 0x20) {
                            sb.append(String.format("\\u%04x", (int) c));
                        } else {
                            sb.append(c);
                        }
                    }
                }
            }
            return sb.append('"').toString();
        }
        return String.valueOf(o);
    }

    private JBCefJSQuery.Response handle(String json) {
        String action = parseAction(json);
        try {
            if ("openFile".equals(action)) {
                String path = extractPath(json);
                if (path == null || path.isBlank()) {
                    return new JBCefJSQuery.Response(buildResponse(false, null, "path 缺失"), 0, null);
                }
                return onEdt(() -> {
                    VirtualFile vf = LocalFileSystem.getInstance().findFileByPath(path);
                    if (vf == null) {
                        return new JBCefJSQuery.Response(
                            buildResponse(false, null, "文件不存在: " + path), 0, null);
                    }
                    FileEditorManager.getInstance(project).openFile(vf, true);
                    return new JBCefJSQuery.Response(buildResponse(true, "opened", null), 0, null);
                });
            }
            if ("getCurrentFile".equals(action)) {
                return onEdt(() -> {
                    VirtualFile[] files = FileEditorManager.getInstance(project).getSelectedFiles();
                    VirtualFile current = files.length > 0 ? files[0] : null;
                    return new JBCefJSQuery.Response(
                        buildResponse(true, current != null ? current.getPath() : "", null), 0, null);
                });
            }
            if ("listProjectFiles".equals(action)) {
                return handleListProjectFiles(json);
            }
            if ("listWorkspaces".equals(action)) {
                return handleListWorkspaces();
            }
            if ("refresh".equals(action)) {
                browser.getCefBrowser().reload();
                return new JBCefJSQuery.Response(buildResponse(true, "refreshed", null), 0, null);
            }
            // ===== 聊天 API（新架构） =====
            if ("authStatus".equals(action)) {
                // 前端按 data.loggedIn 判定登录态（布尔裸值不满足对象协议）
                JsonObject result = new JsonObject();
                result.addProperty("loggedIn", WebAppSettingsState.getInstance().isLoggedIn());
                return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
            }
            if ("getLastConversation".equals(action)) {
                // 返回上次会话 id，前端据此恢复上次会话（不每次新建）
                JsonObject result = new JsonObject();
                result.addProperty("conversationId", WebAppSettingsState.getInstance().lastConversationId);
                return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
            }
            if ("getAuthToken".equals(action)) {
                // 把登录 token + 后端地址给页面：加号上传文件时页面直接 fetch 后端（CORS 已放开）
                WebAppSettingsState s = WebAppSettingsState.getInstance();
                JsonObject result = new JsonObject();
                result.addProperty("token", s.authToken);
                result.addProperty("baseUrl", s.backendUrl);
                return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
            }
            if ("login".equals(action)) {
                return handleLogin(json);
            }
            if ("logout".equals(action)) {
                WebAppSettingsState.getInstance().clearAuth();
                return new JBCefJSQuery.Response(buildResponse(true, "logged out", null), 0, null);
            }
            if ("getWebApp".equals(action)) {
                return handleGetWebApp();
            }
            if ("listWebApps".equals(action)) {
                return handleListWebApps();
            }
            if ("ensureDefaultApp".equals(action)) {
                return handleEnsureDefaultApp();
            }
            if ("switchWebApp".equals(action)) {
                return handleSwitchWebApp(json);
            }
            if ("listSessions".equals(action)) {
                return handleListSessions();
            }
            if ("updateDialogRound".equals(action)) {
                return handleUpdateDialogRound(json);
            }
            if ("loadMessages".equals(action)) {
                return handleLoadMessages(json);
            }
            if ("send".equals(action)) {
                return handleSend(json);
            }
            if ("stop".equals(action)) {
                return handleStop(json);
            }
            if ("feedback".equals(action)) {
                return handleFeedback(json);
            }
            if ("choice".equals(action)) {
                return handleChoice(json);
            }
            if ("startVoiceRecording".equals(action)) {
                return handleStartVoiceRecording();
            }
            if ("stopVoiceRecording".equals(action)) {
                return handleStopVoiceRecording();
            }
            if (DECLARED_NOT_IMPLEMENTED.contains(action)) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "未实现: " + action), 0, null);
            }
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "未知 action: " + action), 0, null);
        } catch (Exception e) {
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "处理失败: " + e.getMessage()), 0, null);
        }
    }

    /**
     * 在 EDT 上执行 IDE/VFS 操作；已在 EDT 则直接执行，避免 invokeAndWait 自阻塞死锁。
     */
    private JBCefJSQuery.Response onEdt(Supplier<JBCefJSQuery.Response> task) {
        Application application = ApplicationManager.getApplication();
        if (application.isDispatchThread()) {
            return task.get();
        }
        AtomicReference<JBCefJSQuery.Response> ref = new AtomicReference<>();
        application.invokeAndWait(() -> ref.set(task.get()));
        return ref.get();
    }

    private static String extractPath(String json) {
        try {
            com.google.gson.JsonObject obj =
                com.google.gson.JsonParser.parseString(json).getAsJsonObject();
            if (obj.has("payload") && obj.get("payload").isJsonObject()
                && obj.getAsJsonObject("payload").has("path")) {
                return obj.getAsJsonObject("payload").get("path").getAsString();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    // ===== 聊天 API handlers =====

    private static String getStringField(String json, String field) {
        try {
            JsonObject obj = JsonParser.parseString(json).getAsJsonObject();
            if (obj.has("payload") && obj.get("payload").isJsonObject()) {
                JsonObject payload = obj.getAsJsonObject("payload");
                if (payload.has(field) && payload.get(field).isJsonPrimitive()) {
                    return payload.get(field).getAsString();
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static boolean getBooleanField(String json, String field) {
        try {
            JsonObject obj = JsonParser.parseString(json).getAsJsonObject();
            if (obj.has("payload") && obj.get("payload").isJsonObject()) {
                JsonObject payload = obj.getAsJsonObject("payload");
                if (payload.has(field) && payload.get(field).isJsonPrimitive()) {
                    return payload.get(field).getAsBoolean();
                }
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    private JBCefJSQuery.Response handleLogin(String json) {
        String email = getStringField(json, "email");
        String password = getStringField(json, "password");
        if (email == null || password == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "email/password 缺失"), 0, null);
        }
        try {
            JsonObject data = api.login(email, password);
            if (data == null || !data.has("access_token")) {
                // 透传后端真实原因（密码格式校验/凭据错误等），无 message 时用兜底文案
                String reason = data != null && data.has("message")
                    ? data.get("message").getAsString()
                    : "登录失败（账号或密码错误）";
                return new JBCefJSQuery.Response(buildResponse(false, null, reason), 0, null);
            }
            WebAppSettingsState settings = WebAppSettingsState.getInstance();
            settings.authToken = data.get("access_token").getAsString();
            settings.email = email;
            // 返回 { access_token, expire_at }，前端以 data.access_token 判定登录成功并进入主界面
            JsonObject result = new JsonObject();
            result.addProperty("access_token", data.get("access_token").getAsString());
            if (data.has("expire_at") && data.get("expire_at").isJsonPrimitive()) {
                result.addProperty("expire_at", data.get("expire_at").getAsLong());
            }
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp login error", e);
            return new JBCefJSQuery.Response(buildResponse(false, null, "登录异常: " + e.getMessage()), 0, null);
        }
    }

    private JBCefJSQuery.Response handleGetWebApp() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        try {
            JsonObject info = api.getWebApp(settings.webAppToken, settings.authToken);
            JsonObject result = new JsonObject();
            result.addProperty("name", info != null && info.has("name")
                ? info.get("name").getAsString() : "");
            result.addProperty("icon", info != null && info.has("icon")
                ? info.get("icon").getAsString() : "");
            // 当前 web_app_token（前端多 App 切换时标记选中项）
            result.addProperty("token", settings.webAppToken);
            // 应用默认短期记忆轮数（会话未单独设置时生效；后端 app_config.dialog_round，不在顶层）
            Integer dialogRound = readDialogRound(info);
            if (dialogRound != null) result.addProperty("dialogRound", dialogRound);
            // 语音转文字开关（App 设置里开启才显示麦克风按钮）
            result.addProperty("speechToTextEnabled", readSpeechToTextEnabled(info));
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (WebAppApiClient.AuthException e) {
            LOG.warn("WebApp getWebApp auth expired", e);
            return authExpired(e.getMessage());
        } catch (Exception e) {
            LOG.warn("WebApp getWebApp error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "获取应用信息失败: " + e.getMessage()), 0, null);
        }
    }

    /** 读取后端应用信息里的语音转文字开关（app_config.speech_to_text.enable）。 */
    private static boolean readSpeechToTextEnabled(@org.jetbrains.annotations.Nullable JsonObject info) {
        if (info == null) return false;
        try {
            JsonElement cfg = info.get("app_config");
            if (cfg != null && cfg.isJsonObject()) {
                JsonElement stt = cfg.getAsJsonObject().get("speech_to_text");
                if (stt != null && stt.isJsonObject()) {
                    JsonElement enable = stt.getAsJsonObject().get("enable");
                    if (enable != null && enable.isJsonPrimitive() && enable.getAsJsonPrimitive().isBoolean()) {
                        return enable.getAsBoolean();
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    /** 读取后端应用信息里的应用默认短期记忆轮数（app_config.dialog_round，不在顶层）。 */
    private static @Nullable Integer readDialogRound(@Nullable JsonObject info) {
        if (info == null) return null;
        try {
            JsonElement cfg = info.get("app_config");
            if (cfg != null && cfg.isJsonObject()) {
                JsonElement dr = cfg.getAsJsonObject().get("dialog_round");
                if (dr != null && dr.isJsonPrimitive() && dr.getAsJsonPrimitive().isNumber()) {
                    return dr.getAsInt();
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /** 当前账号可用的已发布 App 列表（token/name/icon），前端 App 下拉用。 */
    private JBCefJSQuery.Response handleListWebApps() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        try {
            List<JsonObject> apps = api.listWebApps(settings.authToken);
            JsonArray arr = new JsonArray();
            for (JsonObject a : apps) {
                arr.add(a);
            }
            return new JBCefJSQuery.Response(buildResponse(true, arr, null), 0, null);
        } catch (WebAppApiClient.AuthException e) {
            LOG.warn("WebApp listWebApps auth expired", e);
            return authExpired(e.getMessage());
        } catch (Exception e) {
            LOG.warn("WebApp listWebApps error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "获取应用列表失败: " + e.getMessage()), 0, null);
        }
    }

    /** 兜底：账号无已发布应用时让后端创建+发布一个默认应用，并写入当前 webAppToken。 */
    private JBCefJSQuery.Response handleEnsureDefaultApp() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        try {
            JsonObject info = api.bootstrapWebApp(settings.authToken);
            String token = info != null && info.has("token") && info.get("token").isJsonPrimitive()
                ? info.get("token").getAsString() : "";
            if (token.isBlank()) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "获取默认应用失败"), 0, null);
            }
            settings.webAppToken = token;
            // 应用变了：清掉旧应用的会话 id，避免下次发送带着不属于新应用的会话（后端会报"该会话不存在"）
            settings.lastConversationId = "";
            JsonObject result = new JsonObject();
            result.addProperty("token", token);
            result.addProperty("name", info != null && info.has("name") && info.get("name").isJsonPrimitive()
                ? info.get("name").getAsString() : "");
            result.addProperty("icon", info != null && info.has("icon") && info.get("icon").isJsonPrimitive()
                ? info.get("icon").getAsString() : "");
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (WebAppApiClient.AuthException e) {
            LOG.warn("WebApp ensureDefaultApp auth expired", e);
            return authExpired(e.getMessage());
        } catch (Exception e) {
            LOG.warn("WebApp ensureDefaultApp error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "获取默认应用失败: " + e.getMessage()), 0, null);
        }
    }

    /** 切换到指定 App：写入当前 webAppToken + 清空上次会话，返回新 App 信息。 */
    private JBCefJSQuery.Response handleSwitchWebApp(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String token = getStringField(json, "token");
        if (!settings.isLoggedIn() || token == null || token.isBlank()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少 token"), 0, null);
        }
        try {
            // 先校验 token 有效（getWebApp 对不存在/未发布会抛错）
            JsonObject info = api.getWebApp(token, settings.authToken);
            settings.webAppToken = token;
            settings.lastConversationId = ""; // 换 App 后从该 App 最新会话重新恢复
            JsonObject result = new JsonObject();
            result.addProperty("token", token);
            result.addProperty("name", info != null && info.has("name")
                ? info.get("name").getAsString() : "");
            result.addProperty("icon", info != null && info.has("icon")
                ? info.get("icon").getAsString() : "");
            // 应用默认短期记忆轮数（后端 app_config.dialog_round，不在顶层）
            Integer dialogRound = readDialogRound(info);
            if (dialogRound != null) result.addProperty("dialogRound", dialogRound);
            // 语音转文字开关（App 设置里开启才显示麦克风按钮）
            result.addProperty("speechToTextEnabled", readSpeechToTextEnabled(info));
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp switchWebApp error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "切换应用失败: " + e.getMessage()), 0, null);
        }
    }

    private JBCefJSQuery.Response handleListSessions() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        try {
            List<JsonObject> convs = api.listConversations(settings.webAppToken, settings.authToken);
            JsonArray arr = new JsonArray();
            for (JsonObject c : convs) {
                JsonObject item = new JsonObject();
                item.addProperty("id", c.has("id") ? c.get("id").getAsString() : "");
                item.addProperty("title", c.has("name") ? c.get("name").getAsString() : "");
                item.addProperty("time", c.has("created_at") ? c.get("created_at").getAsString() : "");
                // 会话级短期记忆轮数覆盖（未设置时后端返回 null → 不输出，前端回退应用默认）
                if (c.has("dialog_round") && c.get("dialog_round").isJsonPrimitive()
                    && c.get("dialog_round").getAsJsonPrimitive().isNumber()) {
                    item.addProperty("dialogRound", c.get("dialog_round").getAsJsonPrimitive().getAsInt());
                }
                arr.add(item);
            }
            return new JBCefJSQuery.Response(buildResponse(true, arr, null), 0, null);
        } catch (WebAppApiClient.AuthException e) {
            LOG.warn("WebApp listSessions auth expired", e);
            return authExpired(e.getMessage());
        } catch (Exception e) {
            LOG.warn("WebApp listSessions error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "获取会话列表失败: " + e.getMessage()), 0, null);
        }
    }

    /** 更新当前会话的短期记忆轮数（0-100；null = 跟随应用默认）。 */
    private JBCefJSQuery.Response handleUpdateDialogRound(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String conversationId = getStringField(json, "conversationId");
        String roundRaw = getStringField(json, "dialogRound"); // JsonNull → null
        if (!settings.isLoggedIn() || conversationId == null || conversationId.isBlank()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少会话 id"), 0, null);
        }
        Integer dialogRound = null;
        if (roundRaw != null && !roundRaw.isBlank()) {
            try {
                dialogRound = Integer.parseInt(roundRaw);
            } catch (NumberFormatException e) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "短期记忆轮数格式错误"), 0, null);
            }
        }
        try {
            JsonObject data = api.updateConversationDialogRound(
                settings.webAppToken, conversationId, dialogRound, settings.authToken);
            if (data == null) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "保存会话设置失败"), 0, null);
            }
            JsonObject result = new JsonObject();
            result.addProperty("conversationId", conversationId);
            if (data.has("dialog_round") && data.get("dialog_round").isJsonPrimitive()
                && data.get("dialog_round").getAsJsonPrimitive().isNumber()) {
                result.addProperty("dialogRound", data.get("dialog_round").getAsJsonPrimitive().getAsInt());
            }
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp updateDialogRound error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "保存会话设置失败: " + e.getMessage()), 0, null);
        }
    }

    // ===== @ 提及项目文件 =====

    private JBCefJSQuery.Response handleListProjectFiles(String json) {
        String query = getStringField(json, "query");
        String basePath = project.getBasePath();
        if (basePath == null || basePath.isBlank()) {
            return new JBCefJSQuery.Response(buildResponse(true, new JsonArray(), null), 0, null);
        }
        try {
            List<String> relPaths = scanProjectFiles(Paths.get(basePath));
            List<String> files = filterProjectFiles(relPaths, query, MAX_MENTION_FILES);
            JsonArray arr = new JsonArray();
            for (String rel : files) {
                JsonObject o = new JsonObject();
                int idx = rel.lastIndexOf('/');
                o.addProperty("name", idx >= 0 ? rel.substring(idx + 1) : rel);
                o.addProperty("path", rel);
                arr.add(o);
            }
            return new JBCefJSQuery.Response(buildResponse(true, arr, null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp listProjectFiles error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "列出项目文件失败: " + e.getMessage()), 0, null);
        }
    }

    /** 返回当前打开的 IDEA 项目列表（工作区）。必须在 EDT 上访问 ProjectManager。 */
    private JBCefJSQuery.Response handleListWorkspaces() {
        return onEdt(() -> {
            JsonArray arr = new JsonArray();
            Project[] projects = ProjectManager.getInstance().getOpenProjects();
            for (Project p : projects) {
                String base = p.getBasePath();
                if (base == null || base.isBlank()) continue;
                JsonObject o = new JsonObject();
                o.addProperty("name", p.getName());
                o.addProperty("path", base);
                arr.add(o);
            }
            return new JBCefJSQuery.Response(buildResponse(true, arr, null), 0, null);
        });
    }

    /**
     * 遍历项目根目录收集相对路径列表（跳过噪音目录，带条目/深度上限）。
     * 返回相对路径统一用 '/' 分隔（与前端展示一致）。依赖 java.nio 而非 VFS，
     * 可在非 EDT 线程执行（JBCefJSQuery handler 线程），上限保证耗时可控。
     */
    static List<String> scanProjectFiles(Path root) throws IOException {
        List<String> rel = new ArrayList<>();
        if (root == null || !Files.isDirectory(root)) return rel;
        Deque<Path> stack = new ArrayDeque<>();
        stack.push(root);
        int visited = 0;
        while (!stack.isEmpty() && visited < MAX_SCAN_ENTRIES && rel.size() < MAX_MENTION_FILES) {
            Path dir = stack.pop();
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir)) {
                for (Path p : ds) {
                    if (++visited > MAX_SCAN_ENTRIES) break;
                    if (Files.isDirectory(p)) {
                        if (!SKIP_DIR_NAMES.contains(p.getFileName().toString())
                            && root.relativize(p).getNameCount() <= MAX_SCAN_DEPTH) {
                            stack.push(p);
                        }
                    } else if (Files.isRegularFile(p)) {
                        rel.add(root.relativize(p).toString().replace('\\', '/'));
                        if (rel.size() >= MAX_MENTION_FILES) break;
                    }
                }
            }
        }
        return rel;
    }

    /** 纯逻辑：按 query 子串过滤（不区分大小写）+ 大小写不敏感排序 + 截断（可单测）。 */
    static List<String> filterProjectFiles(List<String> relPaths, @org.jetbrains.annotations.Nullable String query, int max) {
        if (relPaths == null || relPaths.isEmpty() || max <= 0) return new ArrayList<>();
        String q = query == null ? "" : query.trim().toLowerCase();
        List<String> result = new ArrayList<>();
        for (String p : relPaths) {
            if (q.isEmpty() || p.toLowerCase().contains(q)) result.add(p);
        }
        result.sort(String.CASE_INSENSITIVE_ORDER);
        if (result.size() > max) {
            result = new ArrayList<>(result.subList(0, max));
        }
        return result;
    }

    /**
     * 把相对项目根目录的路径解析为真实绝对路径；越界（.. 逃逸 / 绝对路径 /
     * 符号链接指向项目外 / 不存在 / 非常规文件）返回 null。安全边界：只能读项目内文件。
     */
    static @org.jetbrains.annotations.Nullable String resolveProjectPath(String basePath, String relPath) {
        if (basePath == null || relPath == null || relPath.isBlank()) return null;
        Path base;
        try {
            base = Paths.get(basePath).normalize().toAbsolutePath();
        } catch (Exception e) {
            return null;
        }
        Path candidate = base.resolve(relPath).normalize();
        if (!candidate.startsWith(base)) return null;
        try {
            Path realBase = base.toRealPath();
            Path real = candidate.toRealPath(); // 解析符号链接；不存在/不可达会抛异常
            if (!real.startsWith(realBase)) return null;
            if (!Files.isRegularFile(real)) return null;
            return real.toString();
        } catch (IOException e) {
            return null;
        }
    }

    private JBCefJSQuery.Response handleLoadMessages(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String conversationId = getStringField(json, "conversationId");
        if (!settings.isLoggedIn() || conversationId == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少会话 id"), 0, null);
        }
        try {
            List<JsonObject> msgs = api.getMessages(conversationId, settings.authToken);
            return new JBCefJSQuery.Response(
                buildResponse(true, toChatMessages(msgs, conversationId), null), 0, null);
        } catch (WebAppApiClient.AuthException e) {
            LOG.warn("WebApp loadMessages auth expired", e);
            return authExpired(e.getMessage());
        } catch (Exception e) {
            LOG.warn("WebApp loadMessages error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "加载消息失败: " + e.getMessage()), 0, null);
        }
    }

    /**
     * 后端消息行 → 前端 ChatMessage 数组（纯逻辑，可单测）。
     * <p>后端消息行 = 一轮对话：query（用户提问）+ answer（助手回复），字段名与前端
     * ChatMessage（content/role）不一致，且没有 role 字段——直接透传会让历史消息全部
     * 变成 content="" 的 assistant（重新进入时显示空对话）。这里把每行拆成
     * 用户消息 + 助手消息两条，并透传 messageId/latency/totalTokenCount/feedback。
     * <p>后端按 created_at 倒序返回（最新在前），页面按数组顺序渲染（最旧在前），故先反转。
     */
    static JsonArray toChatMessages(List<JsonObject> rows, String conversationId) {
        List<JsonObject> ordered = new java.util.ArrayList<>(rows);
        java.util.Collections.reverse(ordered);
        JsonArray arr = new JsonArray();
        for (JsonObject m : ordered) {
            String id = m.has("id") && m.get("id").isJsonPrimitive() ? m.get("id").getAsString() : "";
            String query = m.has("query") && m.get("query").isJsonPrimitive() ? m.get("query").getAsString() : "";
            String answer = m.has("answer") && m.get("answer").isJsonPrimitive() ? m.get("answer").getAsString() : "";
            if (query != null && !query.isBlank()) {
                JsonObject user = new JsonObject();
                user.addProperty("id", id + "-u");
                user.addProperty("role", "user");
                user.addProperty("content", query);
                user.addProperty("conversationId", conversationId);
                // 历史上传的附件：后端 file_urls = [{id, name, size, extension, url}, ...]，
                // 前端 ChatMessage.files = [{id, label}]，label 取文件名（无 name 时回退 id）。
                // 空数组不输出，避免给每条历史用户消息都挂空 files。
                if (m.has("file_urls") && m.get("file_urls").isJsonArray()) {
                    JsonArray fileUrls = m.getAsJsonArray("file_urls");
                    if (fileUrls.size() > 0) {
                        JsonArray files = new JsonArray();
                        for (JsonElement fe : fileUrls) {
                            if (!fe.isJsonObject()) continue;
                            JsonObject fo = fe.getAsJsonObject();
                            String fid = fo.has("id") && fo.get("id").isJsonPrimitive()
                                ? fo.get("id").getAsString() : "";
                            String name = fo.has("name") && fo.get("name").isJsonPrimitive()
                                ? fo.get("name").getAsString() : "";
                            if (fid.isBlank() && name.isBlank()) continue;
                            JsonObject file = new JsonObject();
                            file.addProperty("id", fid);
                            file.addProperty("label", name.isBlank() ? fid : name);
                            files.add(file);
                        }
                        if (files.size() > 0) {
                            user.add("files", files);
                        }
                    }
                }
                arr.add(user);
            }
            // 终态（stop/timeout/error）即使 answer 为空也渲染——它们是"发生过、可查看/可续跑"的一轮，
            // 且 can_resume 需透传给前端显示"继续执行"按钮。
            String status = m.has("status") && m.get("status").isJsonPrimitive()
                ? m.get("status").getAsString() : "";
            boolean isTerminal = "stop".equals(status) || "timeout".equals(status) || "error".equals(status);
            if ((answer != null && !answer.isBlank()) || isTerminal) {
                JsonObject assistant = new JsonObject();
                assistant.addProperty("id", id);
                assistant.addProperty("messageId", id);
                assistant.addProperty("conversationId", conversationId);
                assistant.addProperty("role", "assistant");
                assistant.addProperty("content", answer == null ? "" : answer);
                copyNumber(m, assistant, "latency", "latency");
                copyNumber(m, assistant, "total_token_count", "totalTokenCount");
                if (m.has("feedback") && m.get("feedback").isJsonPrimitive()) {
                    assistant.addProperty("feedback", m.get("feedback").getAsString());
                }
                if (!status.isBlank()) assistant.addProperty("status", status);
                if (m.has("run_status") && m.get("run_status").isJsonPrimitive()) {
                    assistant.addProperty("runStatus", m.get("run_status").getAsString());
                }
                if (m.has("can_resume") && m.get("can_resume").isJsonPrimitive()) {
                    assistant.addProperty("canResume", m.get("can_resume").getAsBoolean());
                }
                arr.add(assistant);
            }
        }
        return arr;
    }

    /** 复制数值字段（同/异名），字段缺失或非数值时忽略。 */
    private static void copyNumber(JsonObject from, JsonObject to, String fromKey, String toKey) {
        if (from.has(fromKey) && from.get(fromKey).isJsonPrimitive()
            && from.get(fromKey).getAsJsonPrimitive().isNumber()) {
            to.addProperty(toKey, from.get(fromKey).getAsJsonPrimitive().getAsNumber());
        }
    }

    private JBCefJSQuery.Response handleSend(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String query = getStringField(json, "query");
        String conversationId = getStringField(json, "conversationId");
        // 断点续跑：透传前端传来的 resume 标记 + 原始消息 id
        boolean resume = getBooleanField(json, "resume");
        String resumeMessageId = getStringField(json, "resumeMessageId");
        // 对话模式:agent=智能体(可操作当前项目文件/执行命令) / chat=纯聊天(默认,兼容旧 auto)
        String mode = getStringField(json, "mode");
        if (mode == null || mode.isBlank()) mode = "chat";
        if ("auto".equals(mode)) mode = "chat"; // 兼容旧前端值
        if (!"agent".equals(mode) && !"chat".equals(mode)) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "mode 只能是 agent/chat"), 0, null);
        }
        final String finalMode = mode;
        JsonArray fileIds = getArrayField(json, "fileIds");
        JsonArray projectFilePaths = getArrayField(json, "projectFilePaths");
        if (!settings.isLoggedIn() || query == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少 query"), 0, null);
        }
        // Agent 模式必须能拿到当前项目根目录（工作区工具的工作目录）
        final String projectRoot;
        if ("agent".equals(mode)) {
            String base = getStringField(json, "projectRoot");
            if (base == null || base.isBlank()) base = project.getBasePath();
            if (base == null || base.isBlank()) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "Agent 模式需要打开项目（文件夹），请先打开项目再使用"), 0, null);
            }
            projectRoot = base;
            // 本地工具运行时：记录当前工作区，供 SSE 线程的 local_tool_call 本地执行
            currentProjectRoot = base;
        } else {
            projectRoot = "";
            currentProjectRoot = "";
        }
        final List<String> ids = new ArrayList<>();
        if (fileIds != null) {
            for (com.google.gson.JsonElement e : fileIds) {
                if (e != null && e.isJsonPrimitive()) ids.add(e.getAsString());
            }
        }
        // 1) 同步上传 @ 提及的项目文件（复用后端上传通道 → 上传 id 并入 file_ids）。
        //    失败直接返回错误，前端据此弹框提示；成功后才发起 chat（见下方异步线程）。
        if (projectFilePaths != null && projectFilePaths.size() > 0) {
            if (ids.size() + projectFilePaths.size() > MAX_TOTAL_FILE_IDS) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "附件数量不能超过" + MAX_TOTAL_FILE_IDS + "个"), 0, null);
            }
            String basePath = getStringField(json, "projectRoot");
            if (basePath == null || basePath.isBlank()) basePath = project.getBasePath();
            if (basePath == null || basePath.isBlank()) {
                return new JBCefJSQuery.Response(
                    buildResponse(false, null, "当前项目无根目录，无法上传项目文件"), 0, null);
            }
            for (com.google.gson.JsonElement e : projectFilePaths) {
                if (e == null || !e.isJsonPrimitive()) continue;
                String rel = e.getAsString();
                if (rel == null || rel.isBlank()) continue;
                String abs = resolveProjectPath(basePath, rel);
                if (abs == null) {
                    return new JBCefJSQuery.Response(
                        buildResponse(false, null, "项目文件路径不合法: " + rel), 0, null);
                }
                try {
                    if (Files.size(Paths.get(abs)) > MAX_PROJECT_FILE_BYTES) {
                        return new JBCefJSQuery.Response(
                            buildResponse(false, null, "项目文件过大（超过10MB）: " + rel), 0, null);
                    }
                    JsonObject up = api.uploadFile(settings.authToken, abs);
                    if (up == null || !up.has("id") || up.get("id").getAsString().isBlank()) {
                        return new JBCefJSQuery.Response(
                            buildResponse(false, null, "上传项目文件失败: " + rel), 0, null);
                    }
                    ids.add(up.get("id").getAsString());
                } catch (Exception ex) {
                    LOG.warn("WebApp upload project file error: " + rel, ex);
                    return new JBCefJSQuery.Response(
                        buildResponse(false, null, "上传项目文件失败: " + rel + "（" + ex.getMessage() + "）"), 0, null);
                }
            }
        }
        // 2) 发起 SSE 流式对话（不阻塞当前线程，事件推回页面）
        lastLatency = 0;
        lastTotalTokens = 0;
        // 60s 超时保护：部分输入后端 agent 可能不返回（流一直不结束），
        // 超时后给前端明确错误提示，避免界面无限等待/出现空框。
        // 例外：agent 调 ask_user 等待用户选择（最长 300s）期间不视为超时，
        // 收到 ASK_USER 事件后挂起超时检查，直到流结束或收到 error。
        new Thread(() -> {
            try {
                java.util.concurrent.CompletableFuture<Void> f =
                    java.util.concurrent.CompletableFuture.runAsync(() -> {
                        try {
                            api.chat(settings.webAppToken, settings.authToken,
                                conversationId == null ? "" : conversationId, query, ids,
                                finalMode, projectRoot,
                                "agent".equals(finalMode) && !currentProjectRoot.isBlank(),
                                this::pushSseEvent,
                                resume, resumeMessageId);
                            pushEvent("messageEnd", null);
                        } catch (Exception e) {
                            LOG.warn("WebApp chat error", e);
                            // 连接被重置/断开（readLine 抛 IOException）会终止本次 SSE 监听，
                            // 后续 local_tool_call 全部丢失 → 服务器 wait_for_tool_result 只能超时。
                            // 这里复位 pending 并把"连接断开/超时 → 请重试"明确回显给用户，
                            // 避免界面停在"等待中"或只有一句技术性错误。
                            askUserPending.set(false);
                            localToolPending.set(false);
                            JsonObject err = new JsonObject();
                            String msg = e.getMessage() == null ? String.valueOf(e) : e.getMessage();
                            err.addProperty("message",
                                "连接已断开（回复超时），本地工具结果可能未回传，请重试。详情：" + msg);
                            pushEvent("error", err.toString());
                        }
                    });
                while (true) {
                    try {
                        f.get(60, java.util.concurrent.TimeUnit.SECONDS);
                        break; // 流正常结束
                    } catch (java.util.concurrent.TimeoutException te) {
                        // ask_user / 本地工具等待期间不算超时（后端 ASK_USER_WAIT_TIMEOUT=300s）。
                        // idleAgoMs：距最近一次收到 SSE 帧/心跳的毫秒数——持续增长 = 服务端静默/连接假死；
                        // 冻结在 ~10s 内 = 读线程仍在收 ping；结合 [sse-write] seq 可定位断点。
                        if (askUserPending.get() || localToolPending.get()) {
                            LOG.warn("WebApp chat waiting for ask_user/local_tool, continue"
                                + " (askUserPending=" + askUserPending.get()
                                + " localToolPending=" + localToolPending.get()
                                + " idleAgoMs=" + (System.currentTimeMillis() - lastActivityAt) + ")");
                            continue;
                        }
                        // 空闲超时：最近仍有事件（含 ping 心跳）就继续，避免编排规划/工具等待误杀
                        if (System.currentTimeMillis() - lastActivityAt < 60_000L) {
                            LOG.warn("WebApp chat still active, continue (idle timeout reset)");
                            continue;
                        }
                        LOG.warn("WebApp chat timeout after 60s idle");
                        pushEvent("error", errorJson("回复超时，请重试"));
                        break;
                    }
                }
            } catch (WebAppApiClient.AuthException e) {
                LOG.warn("WebApp chat auth expired", e);
                authExpired(e.getMessage());
            } catch (Exception e) {
                LOG.warn("WebApp chat wrapper error", e);
                pushEvent("error", errorJson("回复失败: " + e.getMessage()));
            }
        }, "webapp-chat").start();
        return new JBCefJSQuery.Response(buildResponse(true, "started", null), 0, null);
    }

    private JBCefJSQuery.Response handleStop(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String taskId = getStringField(json, "taskId");
        if (!settings.isLoggedIn() || taskId == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少 taskId"), 0, null);
        }
        new Thread(() -> {
            try {
                api.stop(settings.webAppToken, settings.authToken, taskId);
            } catch (Exception e) {
                LOG.warn("WebApp stop error", e);
            }
        }, "webapp-stop").start();
        return new JBCefJSQuery.Response(buildResponse(true, "stopping", null), 0, null);
    }

    // ===== 消息反馈（点赞/点踩） =====

    private JBCefJSQuery.Response handleFeedback(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String conversationId = getStringField(json, "conversationId");
        String messageId = getStringField(json, "messageId");
        String feedback = getStringField(json, "feedback");
        if (!settings.isLoggedIn() || conversationId == null || messageId == null || feedback == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "参数缺失或未登录"), 0, null);
        }
        try {
            api.feedback(conversationId, messageId, feedback, settings.authToken);
            return new JBCefJSQuery.Response(buildResponse(true, "ok", null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp feedback error", e);
            return new JBCefJSQuery.Response(buildResponse(false, null, "反馈提交失败"), 0, null);
        }
    }

    // ===== ask_user 选择 / 计划确认 =====

    private JBCefJSQuery.Response handleChoice(String json) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String taskId = getStringField(json, "taskId");
        String eventId = getStringField(json, "eventId");
        String action = getStringField(json, "action");   // plan 模式: confirm / replan
        String choice = getStringField(json, "choice");   // option 模式
        String custom = getStringField(json, "custom");
        String skipRaw = getStringField(json, "skip");
        if (!settings.isLoggedIn() || taskId == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录或缺少 taskId"), 0, null);
        }
        JsonObject body = new JsonObject();
        if (action != null) {
            body.addProperty("action", action);
            JsonArray keepOrders = getArrayField(json, "keepOrders");
            body.add("keep_orders", keepOrders == null ? new JsonArray() : keepOrders);
            body.addProperty("custom", custom == null ? "" : custom);
        } else {
            body.addProperty("choice", choice == null ? "" : choice);
            body.addProperty("custom", custom == null ? "" : custom);
        }
        body.addProperty("skip", "true".equals(skipRaw));
        if (eventId != null && !eventId.isBlank()) {
            body.addProperty("event_id", eventId);
        }
        new Thread(() -> {
            try {
                api.choice(settings.webAppToken, taskId, body, settings.authToken);
            } catch (Exception e) {
                LOG.warn("WebApp choice error", e);
            }
        }, "webapp-choice").start();
        return new JBCefJSQuery.Response(buildResponse(true, "submitted", null), 0, null);
    }

    // ===== 语音输入（Java 侧录音 → 上传 MinIO → 转文字） =====

    /** 开始录音：javax.sound 采集系统默认输入设备。 */
    private JBCefJSQuery.Response handleStartVoiceRecording() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        try {
            voiceRecorder.start();
            return new JBCefJSQuery.Response(buildResponse(true, "started", null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp voice start error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "无法访问麦克风（可能被占用或无输入设备）"), 0, null);
        }
    }

    /**
     * 停止录音 → 写临时 WAV → 走现有上传通道（/upload-files/file，存 MinIO 拿 key）→
     * /audio/audio_to_text 直接识别 → 返回 {text}。同步返回，前端回填输入框。
     */
    private JBCefJSQuery.Response handleStopVoiceRecording() {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未登录"), 0, null);
        }
        byte[] wav = voiceRecorder.stopAndGetWav();
        if (wav == null) {
            return new JBCefJSQuery.Response(buildResponse(false, null, "未录到声音"), 0, null);
        }
        java.nio.file.Path tmp = null;
        try {
            tmp = java.nio.file.Files.createTempFile("webapp-voice", ".wav");
            java.nio.file.Files.write(tmp, wav);
            JsonObject up = api.uploadFile(settings.authToken, tmp.toString());
            if (up == null || !up.has("key") || up.get("key").getAsString().isBlank()) {
                return new JBCefJSQuery.Response(buildResponse(false, null, "音频上传失败"), 0, null);
            }
            String text = api.audioToText(settings.authToken, up.get("key").getAsString());
            if (text == null) {
                return new JBCefJSQuery.Response(buildResponse(false, null, "语音识别失败"), 0, null);
            }
            JsonObject result = new JsonObject();
            result.addProperty("text", text);
            return new JBCefJSQuery.Response(buildResponse(true, result, null), 0, null);
        } catch (Exception e) {
            LOG.warn("WebApp voice transcribe error", e);
            return new JBCefJSQuery.Response(
                buildResponse(false, null, "语音转文字失败: " + e.getMessage()), 0, null);
        } finally {
            if (tmp != null) {
                try {
                    java.nio.file.Files.deleteIfExists(tmp);
                } catch (Exception ignored) {
                }
            }
        }
    }

    /** 读取 payload 中的 JSON 数组字段（keepOrders 等）。 */
    private static @org.jetbrains.annotations.Nullable JsonArray getArrayField(String json, String field) {
        try {
            JsonObject obj = JsonParser.parseString(json).getAsJsonObject();
            if (obj.has("payload") && obj.get("payload").isJsonObject()) {
                JsonObject payload = obj.getAsJsonObject("payload");
                if (payload.has(field) && payload.get(field).isJsonArray()) {
                    return payload.getAsJsonArray(field);
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    // ===== SSE 事件推送回页面 =====

    /** 最近一次 agent_message 携带的统计：最后一个 agent_message 带消息级总量，END 时推给前端。 */
    private double lastLatency = 0;
    private long lastTotalTokens = 0;

    /**
     * 处理服务器下发的 local_tool_call：在插件本地执行 fs_* 文件工具（读 + 写/改/建/复制/移动/删除），
     * 并把结果回传给 /web_apps/{token}/chat/{task_id}/tool-result（含 tool_call_id 关联）。
     *
     * 看门狗语义（防卡死串行 + 防 SSE 断流静默丢结果）：
     *   1) 本方法在单线程 localToolExecutor 的 worker 线程上执行（SSE 线程只入队不阻塞）；
     *   2) 执行前先登记一条看门狗任务：若"执行 + 回传"超过 LOCAL_TOOL_WATCHDOG_TIMEOUT_MS
     *      （默认 40s，小于服务器 60s 等待上限）仍未完成，由看门狗线程尽力 POST 一次超时错误
     *      给服务器，服务器可提前解除 wait_for_tool_result，后续排队中的本地工具不被串行拖死；
     *   3) worker / 看门狗通过 CAS(posted) 保证同一 tool_call_id 只会回传一次结果。
     */
    private void handleLocalToolCall(SseEventParser.ParsedEvent parsed) {
        JsonObject raw = parsed.raw();
        if (raw == null) {
            // 帧解析失败（服务端历史截断/传输问题）会导致 task/tool_call_id 全缺失：
            // 无法回传结果，服务器将等到 60s 超时。此处必须打日志显性化，避免"静默丢失工具"。
            LOG.warn("WebApp local_tool_call 帧解析失败（data 为空/非法 JSON，可能被服务端截断），"
                + "本次本地工具调用被丢弃——服务端将等待至超时；请同步排查 sse_format 截断");
            return;
        }
        String taskId = getString(raw, "task_id");
        String toolCallId = getString(raw, "tool_call_id");
        String tool = getString(raw, "tool");
        JsonElement ti = raw.get("tool_input");
        JsonObject toolInput = (ti != null && ti.isJsonObject()) ? ti.getAsJsonObject() : new JsonObject();
        if (taskId == null || taskId.isBlank() || toolCallId == null || toolCallId.isBlank() || tool == null || tool.isBlank()) {
            LOG.warn("WebApp local_tool_call 缺少关键字段 task_id=" + taskId
                + " tool_call_id=" + toolCallId + " tool=" + tool
                + "（帧 dataLen=" + (parsed.raw() == null ? -1 : parsed.raw().toString().length())
                + "，可能被截断）——已丢弃，无法回传");
            pushEvent("error", errorJson("本地工具调用缺少 task_id/tool_call_id/tool"));
            return;
        }
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        String projectRoot = currentProjectRoot;
        LOG.info("WebApp handleLocalToolCall start tool=" + tool
            + " task=" + taskId + " tool_call_id=" + toolCallId
            + " projectRoot=" + (projectRoot == null ? "" : projectRoot));
        java.util.concurrent.atomic.AtomicBoolean posted = new java.util.concurrent.atomic.AtomicBoolean(false);

        // 看门狗：40s 内执行+回传未完成 → 尽力 POST 超时错误（独立于 SSE，能提前解除服务器等待）
        localToolWatchdog.schedule(() -> {
            if (posted.get()) return;
            LOG.warn("WebApp local tool watchdog fired: tool=" + tool + " tool_call_id=" + toolCallId
                + " (>" + (LOCAL_TOOL_WATCHDOG_TIMEOUT_MS / 1000) + "s 未完成)，尽力回传超时错误");
            postToolResult(posted, settings, taskId, toolCallId, tool, "",
                "本地工具执行超时（插件看门狗 " + (LOCAL_TOOL_WATCHDOG_TIMEOUT_MS / 1000) + "s 未完成）", "watchdog");
        }, LOCAL_TOOL_WATCHDOG_TIMEOUT_MS, java.util.concurrent.TimeUnit.MILLISECONDS);

        try {
            String result = (projectRoot == null || projectRoot.isBlank())
                ? LocalToolRuntime.execute(null, tool, toolInput)
                : LocalToolRuntime.execute(projectRoot, tool, toolInput);
            String error = (projectRoot == null || projectRoot.isBlank()) ? "未选择本地工作区" : "";
            postToolResult(posted, settings, taskId, toolCallId, tool, result, error, "worker");
        } catch (Exception e) {
            LOG.warn("WebApp handleLocalToolCall error tool=" + tool, e);
            postToolResult(posted, settings, taskId, toolCallId, tool, "",
                e.getMessage() == null ? String.valueOf(e) : e.getMessage(), "worker");
        }
    }

    /**
     * 回传工具结果（CAS 保证同 tool_call_id 只回传一次：worker 完成与看门狗超时竞争时只有一个胜出）。
     */
    private void postToolResult(java.util.concurrent.atomic.AtomicBoolean posted,
                                @NotNull WebAppSettingsState settings,
                                @NotNull String taskId, @NotNull String toolCallId, @NotNull String tool,
                                @NotNull String result, @NotNull String error, @NotNull String tag) {
        if (!posted.compareAndSet(false, true)) {
            LOG.warn("WebApp local tool result already posted (tag=" + tag + ") tool=" + tool
                + " tool_call_id=" + toolCallId + " — 丢弃本次回传");
            return;
        }
        boolean ok = api.submitToolResult(settings.webAppToken, settings.authToken,
            taskId, toolCallId, result, error);
        if (!ok) pushToolTimeout(tool);
    }

    /**
     * 本地工具结果回传重试后仍失败（服务器 wait_for_tool_result 约 60s 后会判超时）时，
     * 向用户界面即时推送一条"执行超时/请重试"提醒，避免用户只见"莫名中断"。
     */
    private void pushToolTimeout(@NotNull String tool) {
        JsonObject data = new JsonObject();
        data.addProperty("content", "⏱️ 本地工具 " + tool + " 执行超时/结果回传失败（已自动重试）。请重试该操作；"
            + "若持续失败，请确认插件已更新并重启 IDE。");
        pushEvent("messageDelta", data.toString());
    }

    private static String getString(@Nullable JsonObject obj, @NotNull String key) {
        if (obj == null || !obj.has(key) || !obj.get(key).isJsonPrimitive()) return null;
        return obj.get(key).getAsString();
    }

    private void pushSseEvent(WebAppApiClient.ChatEvent evt) {
        lastActivityAt = System.currentTimeMillis();
        SseEventParser.ParsedEvent parsed = SseEventParser.parse(evt.eventName(), evt.data());
        // 断流定位日志：只记粗粒度事件（ask_user / local_tool_call / end / error / agent_action 等），
        // 忽略 MESSAGE_DELTA(每 token chunk) 与 IGNORE(ping 心跳)——配合服务端 [sse-write] 的 seq，
        // 可判断事件是"服务端没发出"还是"发出后插件没收到"。
        SseEventParser.Kind kind = parsed.kind();
        if (kind != SseEventParser.Kind.MESSAGE_DELTA && kind != SseEventParser.Kind.IGNORE) {
            LOG.info("WebApp SSE recv kind=" + kind + " event=" + evt.eventName()
                + " seq=" + evt.seqId()
                + " dataLen=" + (evt.data() == null ? 0 : evt.data().length()));
        }
        // 记录最近会话 id（持久化）：下次打开插件恢复上次会话，而不是每次新建
        if (parsed.conversationId() != null && !parsed.conversationId().isBlank()) {
            WebAppSettingsState settings = WebAppSettingsState.getInstance();
            if (!parsed.conversationId().equals(settings.lastConversationId)) {
                settings.lastConversationId = parsed.conversationId();
            }
        }
        switch (parsed.kind()) {
            case MESSAGE_DELTA -> {
                // 跟踪统计字段：react/orchestrator 在结束前的最后一个 agent_message 里带
                // 消息级 latency / total_token_count（增量 chunk 的统计不全，最后一条覆盖）
                JsonObject raw = parsed.raw();
                if (raw != null) {
                    if (raw.has("latency") && raw.get("latency").isJsonPrimitive()
                        && raw.get("latency").getAsJsonPrimitive().isNumber()) {
                        lastLatency = raw.get("latency").getAsDouble();
                    }
                    if (raw.has("total_token_count") && raw.get("total_token_count").isJsonPrimitive()
                        && raw.get("total_token_count").getAsJsonPrimitive().isNumber()) {
                        lastTotalTokens = raw.get("total_token_count").getAsLong();
                    }
                }
                pushEvent("messageDelta", deltaJson(parsed));
            }
            case END -> {
                askUserPending.set(false);
                localToolPending.set(false);
                pushEvent("messageEnd", endStatsJson());
            }
            case ERROR -> {
                askUserPending.set(false);
                localToolPending.set(false);
                pushEvent("error", errorJson(parsed.content()));
            }
            case ASK_USER -> {
                // agent 等待用户选择：超时保护放行，直到用户提交 choice 或流结束
                askUserPending.set(true);
                pushEvent("askUser", askUserJson(parsed));
            }
            case LOCAL_TOOL_CALL -> {
                // 本地工具运行时：在插件本地执行并回传结果。
                // 关键：不可在这个 SSE 消费线程上同步执行——handleLocalToolCall 会做
                // 文件 I/O + result 回传（HTTP），一旦卡住会拖住整个 SSE 读取，
                // 导致后续事件堆积 / SSE 连接被服务器断开（表现为个别 local_tool_call 丢失）。
                // 这里投递到独立单线程执行器，SSE 消费线程立刻返回继续读事件。
                localToolPending.set(true);
                localToolExecutor.execute(() -> handleLocalToolCall(parsed));
            }
            case THOUGHT, IGNORE -> {
                // 第一版不渲染 thought 细节
            }
        }
    }

    /** messageEnd 数据：把最后一条 agent_message 的耗时/token 统计带给前端实时消息。 */
    private String endStatsJson() {
        JsonObject o = new JsonObject();
        if (lastLatency > 0) o.addProperty("latency", lastLatency);
        if (lastTotalTokens > 0) o.addProperty("totalTokenCount", lastTotalTokens);
        return o.toString();
    }

    private void pushEvent(String type, String dataJson) {
        if (browser == null || browser.getCefBrowser() == null) return;
        // 协议：window.__agentChatEvent(JSON.stringify({ type, data }))——必须传 JSON 字符串，
        // 前端 handler 会 JSON.parse；传对象字面量会导致 parse 抛异常被吞，事件全部丢失。
        StringBuilder js = new StringBuilder();
        js.append("window.__agentChatEvent && window.__agentChatEvent(JSON.stringify(");
        js.append("{\"type\":\"").append(type).append("\"");
        if (dataJson != null) {
            js.append(",\"data\":").append(dataJson);
        }
        js.append("}))");
        browser.getCefBrowser().executeJavaScript(js.toString(), browser.getCefBrowser().getURL(), 0);
    }

    /** 鉴权失败（token 过期/无效）：清登录态 + 通知前端切回登录页，并返回错误响应。 */
    private JBCefJSQuery.Response authExpired(@Nullable String message) {
        WebAppSettingsState.getInstance().clearAuth();
        String msg = message == null || message.isBlank() ? "登录已过期，请重新登录" : message;
        JsonObject data = new JsonObject();
        data.addProperty("message", msg);
        pushEvent("sessionExpired", data.toString());
        return new JBCefJSQuery.Response(buildResponse(false, null, msg), 0, null);
    }

    /**
     * 把文本填入聊天输入框（编辑器右键菜单"自定义"用）：
     * 复用宿主→webview 事件通道，前端 AgentChatEmbed 收到 setComposerText 后回填输入框，不发送。
     */
    public void setComposerText(@NotNull String text) {
        if (text == null || text.isEmpty()) return;
        JsonObject data = new JsonObject();
        data.addProperty("text", text);
        pushEvent("setComposerText", data.toString());
    }

    /**
     * 编辑器选中代码的 AI 操作（优化/解释/注释）：调后端 code_action，返回 {code, explanation}。
     * 供编辑器右键菜单 AnAction 调用（复用登录态与后端地址配置）。
     *
     * @return 成功：{code, explanation}；未登录/失败：null
     */
    public @Nullable JsonObject codeAction(
        @NotNull String action,
        @NotNull String code,
        @NotNull String language) {
        WebAppSettingsState settings = WebAppSettingsState.getInstance();
        if (!settings.isLoggedIn()) return null;
        try {
            return api.codeAction(settings.webAppToken, settings.authToken, action, code, language);
        } catch (Exception e) {
            LOG.warn("WebApp codeAction error", e);
            return null;
        }
    }

    private static String deltaJson(SseEventParser.ParsedEvent evt) {
        JsonObject o = new JsonObject();
        o.addProperty("content", evt.content());
        if (evt.taskId() != null) o.addProperty("taskId", evt.taskId());
        if (evt.runId() != null) o.addProperty("runId", evt.runId());
        if (evt.conversationId() != null) o.addProperty("conversationId", evt.conversationId());
        if (evt.messageId() != null) o.addProperty("messageId", evt.messageId());
        return o.toString();
    }

    /** ask_user 事件：把 question/options/sub_task_options 等结构化数据推给前端渲染。 */
    private static String askUserJson(SseEventParser.ParsedEvent evt) {
        JsonObject o = new JsonObject();
        o.addProperty("taskId", evt.taskId() == null ? "" : evt.taskId());
        if (evt.runId() != null) o.addProperty("runId", evt.runId());
        JsonObject raw = evt.raw();
        if (raw != null) {
            if (raw.has("id") && raw.get("id").isJsonPrimitive()) {
                o.addProperty("eventId", raw.get("id").getAsString());
            }
            copyString(raw, o, "question");
            copyString(raw, o, "choice");
            // 前端 AskUserInfo 使用驼峰 allowCustom；后端事件字段是下划线 allow_custom，需显式转换
            if (raw.has("allow_custom") && raw.get("allow_custom").isJsonPrimitive()) {
                o.addProperty("allowCustom", raw.get("allow_custom").getAsBoolean());
            }
            if (raw.has("options") && raw.get("options").isJsonArray()) {
                o.add("options", raw.get("options"));
            }
            boolean isPlan = raw.has("sub_task_options")
                && raw.get("sub_task_options").isJsonArray()
                && raw.getAsJsonArray("sub_task_options").size() > 0;
            if (isPlan) {
                o.add("subTaskOptions", raw.get("sub_task_options"));
            }
            o.addProperty("mode", isPlan ? "plan" : "option");
        }
        if (!o.has("eventId")) o.addProperty("eventId", "");
        if (!o.has("allowCustom")) o.addProperty("allowCustom", true);
        return o.toString();
    }

    private static void copyString(JsonObject from, JsonObject to, String key) {
        if (from.has(key) && from.get(key).isJsonPrimitive()) {
            to.addProperty(key, from.get(key).getAsString());
        }
    }

    private static void copyBool(JsonObject from, JsonObject to, String key) {
        if (from.has(key) && from.get(key).isJsonPrimitive()) {
            to.addProperty(key, from.get(key).getAsBoolean());
        }
    }

    private static String errorJson(String message) {
        JsonObject o = new JsonObject();
        o.addProperty("message", message == null ? "" : message);
        return o.toString();
    }

    @Override
    public void dispose() {
        if (jsQuery != null) {
            // IU 2024.2 中 removeHandler 需传入注册时的 handler；无参重载不存在
            jsQuery.removeHandler(handler);
            jsQuery.dispose();
            jsQuery = null;
        }
        localToolExecutor.shutdownNow();
        localToolWatchdog.shutdownNow();
    }
}
