package com.webapp.plugin.util;

import com.intellij.openapi.application.PathManager;
import org.jetbrains.annotations.NotNull;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.FileSystem;
import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Comparator;
import java.util.stream.Stream;

/**
 * 把插件 jar 内打包的 Web UI 资源（resources/web-ui/）解压到系统目录，
 * 供 JCEF 以自定义 scheme（http://agent-chat/）加载。
 */
public final class WebUiResourceLoader {

    /** jar 内资源根路径（resources/web-ui/）。 */
    private static final String RESOURCE_ROOT = "/web-ui";

    private WebUiResourceLoader() {
    }

    /**
     * 确保 web-ui 已解压到系统目录，返回其根路径。
     * 兼容两种 jar 内结构：
     * - web-ui/index.html（vite outDir=dist 直接同步）
     * - web-ui/agent-chat-embed/index.html（早期嵌套产物）
     * 每次加载都从 jar 重新解压（REPLACE_EXISTING），保证插件升级后 UI 即时刷新，
     * 无需手动清理系统目录下的旧缓存。
     */
    public static @NotNull Path extractWebUiRoot() throws IOException {
        Path dest = webUiDir();
        Files.createDirectories(dest);
        copyFromJar(dest);
        // 处理嵌套：index.html 可能在子目录
        if (!Files.exists(dest.resolve("index.html"))) {
            // 递归找 index.html 所在目录作为根
            try (Stream<Path> walk = Files.walk(dest, 3)) {
                Path found = walk.filter(p -> p.getFileName().toString().equals("index.html"))
                    .findFirst().orElse(null);
                if (found != null) {
                    return found.getParent();
                }
            }
            throw new IOException("web-ui 中未找到 index.html");
        }
        return dest;
    }

    /**
     * 确保 web-ui 解压完成，返回 index.html 的 file:// URL（供 JCEF 加载）。
     */
    public static @NotNull String extractAndGetIndexUrl() throws IOException {
        Path root = extractWebUiRoot();
        return root.resolve("index.html").toUri().toString();
    }

    private static Path webUiDir() {
        // PathManager.getSystemDir() 返回 Path，直接 resolve 子目录
        return PathManager.getSystemDir()
            .resolve("webapp-plugin")
            .resolve("web-ui");
    }

    /** 从 jar 复制整个 web-ui 目录（含子目录）。 */
    private static void copyFromJar(Path dest) throws IOException {
        java.net.URL resource = WebUiResourceLoader.class.getResource(RESOURCE_ROOT);
        if (resource == null) {
            throw new IOException("jar 中缺少 web-ui 资源（resources/web-ui 为空，"
                + "请先在 ai-llmops-web 执行 vite build 再重新 buildPlugin）");
        }
        URI uri;
        try {
            uri = resource.toURI();
        } catch (URISyntaxException e) {
            throw new IOException("web-ui 资源 URI 解析失败", e);
        }

        // jar 内目录用 FileSystem 遍历；开发态可能是文件系统目录
        if ("jar".equals(uri.getScheme())) {
            copyFromJarFs(uri, dest);
        } else {
            copyFromDir(Paths.get(uri), dest);
        }
    }

    private static void copyFromJarFs(URI jarDirUri, Path dest) throws IOException {
        java.util.Map<String, String> env = java.util.Map.of();
        try (FileSystem fs = FileSystems.newFileSystem(jarDirUri, env)) {
            Path root = fs.getPath(RESOURCE_ROOT);
            try (Stream<Path> walk = Files.walk(root)) {
                for (Path p : (Iterable<Path>) walk::iterator) {
                    if (Files.isDirectory(p)) continue;
                    String rel = root.relativize(p).toString();
                    Path target = dest.resolve(rel);
                    Files.createDirectories(target.getParent());
                    Files.copy(p, target, StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
    }

    private static void copyFromDir(Path srcDir, Path dest) throws IOException {
        try (Stream<Path> walk = Files.walk(srcDir)) {
            for (Path p : (Iterable<Path>) walk::iterator) {
                if (Files.isDirectory(p)) continue;
                String rel = srcDir.relativize(p).toString();
                Path target = dest.resolve(rel);
                Files.createDirectories(target.getParent());
                Files.copy(p, target, StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    /** 清理已解压的 web-ui（可选，未使用）。 */
    public static void cleanup() throws IOException {
        Path dest = webUiDir();
        if (Files.exists(dest)) {
            try (Stream<Path> walk = Files.walk(dest)) {
                for (Path p : (Iterable<Path>) walk.sorted(Comparator.reverseOrder())::iterator) {
                    Files.deleteIfExists(p);
                }
            }
        }
    }
}
