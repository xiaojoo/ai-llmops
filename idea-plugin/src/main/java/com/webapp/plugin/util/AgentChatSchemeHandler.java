package com.webapp.plugin.util;

import com.intellij.openapi.diagnostic.Logger;
import org.cef.browser.CefBrowser;
import org.cef.callback.CefCallback;
import org.cef.handler.CefResourceHandler;
import org.cef.misc.IntRef;
import org.cef.misc.StringRef;
import org.cef.network.CefRequest;
import org.cef.network.CefResponse;
import org.jetbrains.annotations.NotNull;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/**
 * 把 http://agent-chat/... 请求映射到本地解压的 Web UI 文件。
 * JCEF 以自定义 scheme 加载本地资源，避免 file:// 下 module 脚本被安全策略阻止。
 */
public final class AgentChatSchemeHandler implements CefResourceHandler {

    private static final Logger LOG = Logger.getInstance(AgentChatSchemeHandler.class);

    /** 自定义 scheme host。 */
    public static final String HOST = "agent-chat";

    private static final Map<String, String> MIME = Map.of(
        "html", "text/html",
        "js", "application/javascript",
        "css", "text/css",
        "json", "application/json",
        "png", "image/png",
        "jpg", "image/jpeg",
        "svg", "image/svg+xml",
        "ico", "image/x-icon",
        "woff", "font/woff",
        "woff2", "font/woff2"
    );

    private final Path webUiRoot;
    private byte[] data;
    private int offset;
    private String mimeType = "application/octet-stream";

    public AgentChatSchemeHandler(@NotNull Path webUiRoot) {
        this.webUiRoot = webUiRoot;
    }

    /** 处理请求：加载文件内容到内存。返回 true 表示继续（进入 processRequest）。 */
    @Override
    public boolean processRequest(CefRequest request, CefCallback callback) {
        String url = request.getURL();
        try {
            URI uri = URI.create(url);
            String path = uri.getPath();
            if (path == null || path.isEmpty() || "/".equals(path)) {
                path = "/index.html";
            }
            // 去掉前导斜杠，防止路径穿越
            String rel = path.startsWith("/") ? path.substring(1) : path;
            Path file = webUiRoot.resolve(rel).normalize();
            if (!file.startsWith(webUiRoot.normalize())) {
                LOG.warn("WebApp scheme path traversal blocked: " + url);
                callback.cancel();
                return false;
            }
            if (!Files.isRegularFile(file)) {
                LOG.warn("WebApp scheme file not found: " + url);
                callback.cancel();
                return false;
            }
            data = Files.readAllBytes(file);
            offset = 0;
            String ext = extensionOf(rel);
            mimeType = MIME.getOrDefault(ext, "application/octet-stream");
            LOG.info("WebApp scheme serving: " + url + " -> " + file + " (" + data.length + " B, " + mimeType + ")");
            callback.Continue();
            return true;
        } catch (Exception e) {
            LOG.warn("WebApp scheme processRequest error: " + url, e);
            callback.cancel();
            return false;
        }
    }

    @Override
    public void getResponseHeaders(CefResponse response, IntRef responseLength, StringRef redirectUrl) {
        response.setMimeType(mimeType);
        response.setStatus(200);
        // 自定义 scheme 下 module 脚本/样式跨源加载需要 CORS 允许
        response.setHeaderByName("Access-Control-Allow-Origin", "*", true);
        response.setHeaderByName("Cache-Control", "no-cache", true);
        responseLength.set(data != null ? data.length : 0);
    }

    @Override
    public boolean readResponse(byte[] dataOut, int bytesToRead, IntRef bytesRead, CefCallback callback) {
        if (data == null || offset >= data.length) {
            bytesRead.set(0);
            return false;
        }
        int remaining = data.length - offset;
        int toRead = Math.min(remaining, bytesToRead);
        System.arraycopy(data, offset, dataOut, 0, toRead);
        offset += toRead;
        bytesRead.set(toRead);
        return offset < data.length;
    }

    @Override
    public void cancel() {
        data = null;
        offset = 0;
    }

    private static String extensionOf(String path) {
        int dot = path.lastIndexOf('.');
        if (dot < 0) return "";
        return path.substring(dot + 1).toLowerCase();
    }
}
