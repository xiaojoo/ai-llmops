package com.webapp.plugin.util;

import org.jetbrains.annotations.NotNull;

import java.util.Locale;
import java.util.Set;

/**
 * WebApp URL 安全校验：仅允许 http/https，拒绝危险 scheme 与非法字符。
 */
public final class UrlValidator {

    private static final Set<String> ALLOWED_SCHEMES = Set.of("http", "https");

    private UrlValidator() {
    }

    public static boolean isValid(String url) {
        if (url == null || url.isBlank()) {
            return false;
        }
        for (int i = 0; i < url.length(); i++) {
            char c = url.charAt(i);
            if (Character.isWhitespace(c) || Character.isISOControl(c)) {
                return false;
            }
        }
        int colon = url.indexOf(':');
        if (colon <= 0) {
            return false;
        }
        String scheme = url.substring(0, colon).toLowerCase(Locale.ROOT);
        return isValidScheme(scheme);
    }

    public static boolean isValidScheme(String scheme) {
        return scheme != null && ALLOWED_SCHEMES.contains(scheme.toLowerCase(Locale.ROOT));
    }

    public static String normalizeBase(String serverUrl) {
        if (serverUrl == null) {
            return "";
        }
        String s = serverUrl.trim();
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        return s;
    }

    public static String normalizePath(String path) {
        if (path == null) {
            return "";
        }
        String s = path.trim();
        while (s.startsWith("/")) {
            s = s.substring(1);
        }
        return s;
    }

    @NotNull
    public static String buildFullUrl(String serverUrl, String path) {
        String base = normalizeBase(serverUrl);
        String p = normalizePath(path);
        if (base.isEmpty()) {
            return p;
        }
        return p.isEmpty() ? base : base + "/" + p;
    }
}
