package com.webapp.plugin.api;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Local Tool Runtime —— 插件对用户真实本地工作区执行文件工具（Phase 2：读 + 写/改/建/复制/移动/删除）。
 *
 * 背景（Remote Agent + Local Tool Runtime）：服务器 Agent 只在插件进程里执行
 * fs_* 工具，插件是唯一持有绝对路径、唯一做包含性校验的权威。
 *
 * 约定（与 VS Code 侧 localTools.ts、服务器 workspace_tools 语义一致）：
 * - 入参为"相对工作区根"路径；返回 JSON 字符串，结构与服务器 fs_* 响应一致
 * - PathGuard：拒绝绝对路径 / 盘符 / UNC / .. 逃逸 / 符号链接逃逸
 * - 写入/删除语义对齐服务器 FileService：
 *   fs_write/fs_edit/fs_mkdir 写入前做编码/大小校验，父目录自动创建
 *   fs_move/fs_delete 对符号链接"操作链接本身"（follow_final=False，等价 mv/rm 不跟随）
 *   fs_delete 一律先进回收站 .agent-trash/<时间戳>-<随机>/<原相对路径>，可恢复
 *   风险控制：禁止删除工作区根目录、禁止删除工具包内部目录（.agent-trash）
 */
public final class LocalToolRuntime {

    private static final int MAX_READ_BYTES = 2 * 1024 * 1024;
    private static final int MAX_READ_CHARS = 50_000;
    private static final int MAX_LIST_ENTRIES = 500;
    private static final int MAX_SEARCH_RESULTS = 200;
    // 单文件写入/编辑上限（字节），对齐服务器 FileSystemPolicy.max_file_size（默认 2MB）
    private static final long MAX_FILE_SIZE = 2L * 1024 * 1024;
    // 回收站目录名，对齐服务器 FileSystemPolicy.trash_dir_name（.agent-trash）
    private static final String TRASH_DIR_NAME = ".agent-trash";
    private static final Gson GSON = new Gson();

    // 默认排除清单（只读真正的源码；依赖/产物/缓存/IDE/框架元数据一律跳过，大小写不敏感）。
    // 与 VS Code localTools.ts 保持一致。
    private static final java.util.Set<String> SKIP_ENTRIES = java.util.Set.of(
        // VCS / IDE / 编辑器元数据
        ".git", ".svn", ".hg", ".idea", ".vscode", ".vs",
        // Python
        "venv", ".venv", "env", "site-packages", "__pycache__", ".tox", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".pyre", ".mypy", ".eggs", "pip-wheel-metadata",
        // Node / 前端
        "node_modules", ".next", ".nuxt", ".parcel-cache", ".turbo", ".pnpm-store",
        "bower_components", "jspm_packages", "coverage", ".vite", ".output", ".angular",
        ".svelte-kit", ".cache", ".npm", "polyfill",
        // Java / JVM / Gradle / Maven
        "target", "build", "out", "classes", ".gradle", ".mvn", ".settings", ".classpath", ".project",
        // 静态/构建产物
        "dist", ".webpack", ".dart_tool", ".pub-cache", ".tmp");

    // 生成的二进制/编译产物文件扩展名：fs_read 默认不读（只读真正的代码）。
    private static final java.util.Set<String> SKIP_FILE_EXTENSIONS = java.util.Set.of(
        ".pyc", ".pyo", ".class", ".jar", ".war", ".ear", ".min.js", ".map",
        ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".a", ".lib",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".wav", ".avi",
        ".db", ".sqlite", ".sqlite3", ".log", ".tiff");

    private LocalToolRuntime() {
    }

    /** 工具名 → 是否本地运行时支持（Phase 2：全部文件类工具：读 + 写/改/建/复制/移动/删除）。 */
    public static boolean isSupported(@NotNull String tool) {
        return switch (tool) {
            case "fs_list", "fs_stat", "fs_read", "fs_write", "fs_edit",
                 "fs_mkdir", "fs_copy", "fs_move", "fs_delete", "fs_search" -> true;
            default -> false;
        };
    }

    /** 合并后的工作区排除配置（默认=内置清单；用户可经 .webapp/ignore.json 追加）。 */
    private record SkipConfig(java.util.Set<String> dirs, java.util.Set<String> fileExts) {
    }

    /** 内置默认排除配置（只读源码的兜底安全边界）。 */
    static @NotNull SkipConfig defaultSkipConfig() {
        // 复制为可变集合，便于后续追加用户自定义项
        return new SkipConfig(new java.util.HashSet<>(SKIP_ENTRIES), new java.util.HashSet<>(SKIP_FILE_EXTENSIONS));
    }

    /**
     * 读取并合并工作区自定义排除配置（只增不减）：用户添加的 dir/ext 追加到内置清单，
     * 绝不覆盖/移除内置项，避免误删导致读到依赖包/机密。约定：<workspace>/.webapp/ignore.json
     *   { "ignore_dirs": ["target", "*.generated"], "ignore_extensions": [".map", ".tsbuildinfo"] }
     */
    static @NotNull SkipConfig loadWorkspaceSkipConfig(@Nullable String workspace) {
        SkipConfig cfg = defaultSkipConfig();
        if (workspace == null || workspace.isBlank()) return cfg;
        Path ignore = Paths.get(workspace, ".webapp", "ignore.json");
        if (!Files.exists(ignore)) return cfg;
        try {
            JsonObject obj = JsonParser.parseString(Files.readString(ignore, StandardCharsets.UTF_8)).getAsJsonObject();
            if (obj.has("ignore_dirs") && obj.get("ignore_dirs").isJsonArray()) {
                for (com.google.gson.JsonElement e : obj.getAsJsonArray("ignore_dirs")) {
                    if (e.isJsonPrimitive() && !e.getAsString().isBlank()) {
                        cfg.dirs().add(e.getAsString().trim().toLowerCase(Locale.ROOT));
                    }
                }
            }
            if (obj.has("ignore_extensions") && obj.get("ignore_extensions").isJsonArray()) {
                for (com.google.gson.JsonElement e : obj.getAsJsonArray("ignore_extensions")) {
                    if (e.isJsonPrimitive()) {
                        String ext = e.getAsString().trim().toLowerCase(Locale.ROOT);
                        if (!ext.isBlank()) cfg.fileExts().add(ext.startsWith(".") ? ext : "." + ext);
                    }
                }
            }
        } catch (Exception ignored) {
            // 配置缺失/畸形：回落内置清单
        }
        return cfg;
    }

    /** 根据工具名调用本地实现；返回与服务器一致的 JSON 字符串。 */
    public static @NotNull String execute(@Nullable String workspaceRoot, @NotNull String tool,
                                          @Nullable JsonObject args) {
        JsonObject in = args == null ? new JsonObject() : args;
        if (workspaceRoot == null || workspaceRoot.isBlank()) {
            return fail(tool, "NO_WORKSPACE", "未选择本地工作区");
        }
        SkipConfig skip = loadWorkspaceSkipConfig(workspaceRoot);
        return switch (tool) {
            case "fs_list" -> fsList(workspaceRoot, in, skip);
            case "fs_stat" -> fsStat(workspaceRoot, in);
            case "fs_read" -> fsRead(workspaceRoot, in, skip);
            case "fs_write" -> fsWrite(workspaceRoot, in);
            case "fs_edit" -> fsEdit(workspaceRoot, in);
            case "fs_mkdir" -> fsMkdir(workspaceRoot, in);
            case "fs_copy" -> fsCopy(workspaceRoot, in);
            case "fs_move" -> fsMove(workspaceRoot, in);
            case "fs_delete" -> fsDelete(workspaceRoot, in);
            case "fs_search" -> fsSearch(workspaceRoot, in, skip);
            default -> fail(tool, "UNSUPPORTED", "本地工具运行时未支持：" + tool);
        };
    }

    // ===== fs_list =====

    private static @NotNull String fsList(@NotNull String workspace, @NotNull JsonObject args, @NotNull SkipConfig skip) {
        String rel = getString(args, "path", ".");
        boolean showHidden = args.has("show_hidden") && args.get("show_hidden").getAsBoolean();
        // 只列真正的代码：显式列出被排除的依赖/产物目录时也拒绝
        if (!".".equals(rel) && !rel.isBlank() && isInsideSkipped(rel, skip.dirs())) {
            return fail("list", "SKIPPED", "'" + rel + "' 位于被排除的依赖/产物目录，默认不列出（只读源码）", rel);
        }
        Path target = resolveSafe(workspace, rel);
        if (target == null) {
            return fail("list", "INVALID_PATH", "非法路径（仅允许工作区相对路径）");
        }
        if (!Files.exists(target) || !Files.isDirectory(target)) {
            return fail("list", "NOT_DIRECTORY", "'" + rel + "' 不是一个目录", rel);
        }
        try {
            List<Map<String, Object>> items = new ArrayList<>();
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(target)) {
                for (Path p : ds) {
                    String name = p.getFileName().toString();
                    if (!showHidden && name.startsWith(".")) continue;
                    if (isSkippedName(name, skip.dirs())) continue;
                    Map<String, Object> info = entryInfo(workspace, p);
                    items.add(info);
                }
            }
            items.sort((a, b) -> {
                boolean aDir = "directory".equals(a.get("type"));
                boolean bDir = "directory".equals(b.get("type"));
                if (aDir != bDir) return aDir ? -1 : 1;
                return String.valueOf(a.get("name")).compareTo(String.valueOf(b.get("name")));
            });
            int total = items.size();
            boolean truncated = total > MAX_LIST_ENTRIES;
            List<Map<String, Object>> shown = truncated ? items.subList(0, MAX_LIST_ENTRIES) : items;
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("success", true);
            out.put("operation", "list");
            out.put("path", rel);
            out.put("total", total);
            out.put("shown", shown.size());
            out.put("truncated", truncated);
            out.put("entries", shown);
            return GSON.toJson(out);
        } catch (IOException e) {
            return fail("list", "OPERATION_FAILED", "读取目录失败：" + e.getMessage());
        }
    }

    // ===== fs_read =====

    private static @NotNull String fsRead(@NotNull String workspace, @NotNull JsonObject args, @NotNull SkipConfig skip) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("read", "INVALID_PATH", "path 不能为空");
        // 只读真正的代码：落在被排除的依赖/产物目录内，或为生成产物扩展名，一律拒绝
        if (isInsideSkipped(rel, skip.dirs())) {
            return fail("read", "SKIPPED", "'" + rel + "' 位于被排除的依赖/产物目录，默认不读取（只读源码）", rel);
        }
        if (isSkippedFileExtension(rel, skip.fileExts())) {
            return fail("read", "SKIPPED", "'" + rel + "' 为生成/二进制产物，默认不读取（只读源码）", rel);
        }
        Path target = resolveSafe(workspace, rel);
        if (target == null) return fail("read", "INVALID_PATH", "非法路径（仅允许工作区相对路径）", rel);
        try {
            long size = Files.size(target);
            if (Files.isDirectory(target)) return fail("read", "IS_DIRECTORY", "期望文件却得到目录", rel);
            if (size > MAX_READ_BYTES) {
                return fail("read", "SIZE_LIMIT_EXCEEDED", "文件大小超过单次读取上限 " + MAX_READ_BYTES + " 字节", rel);
            }
            String encoding = getString(args, "encoding", "utf-8");
            Charset cs;
            try {
                cs = Charset.forName(encoding);
            } catch (Exception e) {
                return fail("read", "ENCODING_ERROR", "不支持的编码格式：" + encoding, rel);
            }
            String content = Files.readString(target, cs);
            String[] lines = content.split("\n", -1);
            int totalLines = lines.length;
            int start = 1;
            if (args.has("start_line") && args.get("start_line").isJsonPrimitive() && args.get("start_line").getAsJsonPrimitive().isNumber()) {
                start = args.get("start_line").getAsInt();
            }
            int end = totalLines;
            if (args.has("end_line") && args.get("end_line").isJsonPrimitive() && args.get("end_line").getAsJsonPrimitive().isNumber()) {
                end = args.get("end_line").getAsInt();
            }
            if (start < 1) start = 1;
            if (end > totalLines) end = totalLines;
            if (args.has("start_line") && args.has("end_line")
                && args.get("start_line").getAsInt() > args.get("end_line").getAsInt()) {
                return fail("read", "INVALID_ARGUMENT", "start_line 不能大于 end_line", rel);
            }
            int from = Math.max(0, start - 1);
            int to = Math.min(end, totalLines);
            StringBuilder sb = new StringBuilder();
            for (int i = from; i < to; i++) {
                sb.append(lines[i]);
                if (i < to - 1) sb.append('\n');
            }
            String outContent = sb.toString();
            if (outContent.endsWith("\n")) outContent = outContent.substring(0, outContent.length() - 1);
            boolean truncated = outContent.length() > MAX_READ_CHARS;
            if (truncated) outContent = outContent.substring(0, MAX_READ_CHARS);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("success", true);
            out.put("operation", "read");
            out.put("path", toRel(workspace, target));
            out.put("encoding", encoding);
            out.put("size", size);
            out.put("content", outContent);
            out.put("start_line", from + 1);
            out.put("end_line", to);
            out.put("total_lines", totalLines);
            out.put("char_count", outContent.length());
            out.put("truncated", truncated);
            return GSON.toJson(out);
        } catch (IOException e) {
            return fail("read", "OPERATION_FAILED", "读取失败：" + e.getMessage(), rel);
        }
    }

    // ===== fs_search =====

    private static @NotNull String fsSearch(@NotNull String workspace, @NotNull JsonObject args, @NotNull SkipConfig skip) {
        String pattern = getString(args, "pattern", "");
        if (pattern.isBlank()) return fail("search", "INVALID_ARGUMENT", "pattern 不能为空");
        pattern = pattern.replace("\\", "/");
        if (pattern.startsWith("**/")) pattern = pattern.substring(3);
        final String searchPattern = pattern;
        boolean matchByPath = searchPattern.contains("/");
        String rootRel = getString(args, "root", ".");
        boolean includeHidden = args.has("include_hidden") && args.get("include_hidden").getAsBoolean();
        int limitRaw = args.has("limit") && args.get("limit").isJsonPrimitive() && args.get("limit").getAsJsonPrimitive().isNumber()
            ? args.get("limit").getAsInt() : 100;
        final int limit = Math.min(limitRaw, MAX_SEARCH_RESULTS);
        // 只搜真正的代码：搜索起点位于被排除目录时拒绝
        if (!".".equals(rootRel) && !rootRel.isBlank() && isInsideSkipped(rootRel, skip.dirs())) {
            return fail("search", "SKIPPED", "'" + rootRel + "' 位于被排除的依赖/产物目录，默认不搜索（只读源码）", rootRel);
        }
        Path root = resolveSafe(workspace, rootRel);
        if (root == null || !Files.exists(root) || !Files.isDirectory(root)) {
            return fail("search", "NOT_DIRECTORY", "'" + rootRel + "' 不是一个目录", rootRel);
        }
        List<Map<String, Object>> matches = new ArrayList<>();
        int[] totalFound = {0};
        boolean[] truncated = {false};

        java.util.function.Consumer<Path> walk = new java.util.function.Consumer<Path>() {
            @Override
            public void accept(Path dir) {
                if (truncated[0]) return;
                try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir)) {
                    List<Path> sorted = new ArrayList<>();
                    for (Path p : ds) sorted.add(p);
                    sorted.sort((a, b) -> a.getFileName().toString().compareTo(b.getFileName().toString()));
                    for (Path p : sorted) {
                        if (truncated[0]) return;
                        String name = p.getFileName().toString();
                        if (isSkippedName(name, skip.dirs())) continue; // 剪枝：跳过依赖/产物目录，不再进入
                        if (!includeHidden && name.startsWith(".")) continue;
                        boolean isDir = Files.isDirectory(p, LinkOption.NOFOLLOW_LINKS);
                        String rel = toRel(workspace, p);
                        String matched = matchByPath ? rel : name;
                        if (globMatches(matched, searchPattern)) {
                            if (!isDir && isSkippedFileExtension(name, skip.fileExts())) continue; // 生成/二进制产物不计入
                            totalFound[0]++;
                            if (matches.size() >= limit) {
                                truncated[0] = true;
                                return;
                            }
                            Map<String, Object> m = new LinkedHashMap<>();
                            m.put("path", rel);
                            m.put("type", isDir ? "directory" : "file");
                            matches.add(m);
                        }
                        if (isDir) accept(p); // 递归进入子目录
                    }
                } catch (IOException ignored) {
                    // 目录不可读：跳过
                }
            }
        };
        walk.accept(root);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "search");
        out.put("pattern", pattern);
        out.put("root", rootRel);
        out.put("total_found", totalFound[0]);
        out.put("shown", matches.size());
        out.put("truncated", truncated[0]);
        out.put("matches", matches);
        return GSON.toJson(out);
    }

    // ===== 写类工具实现（对齐服务器 FileService 语义） =====

    /** 字节数 → 可读大小（对齐服务器 _fmt_size）。 */
    private static @NotNull String fmtSize(long bytes) {
        double size = Math.max(0, bytes);
        String[] units = {"B", "KB", "MB", "GB", "TB"};
        for (String u : units) {
            if (size < 1024) return String.format(Locale.ROOT, "%.1f %s", size, u);
            size /= 1024;
        }
        return String.format(Locale.ROOT, "%.1f PB", size);
    }

    /** 权限字符串（尽量 posix；Windows 不支持时用只读位兜底）。 */
    private static @NotNull String permissionsOf(@NotNull Path abs) {
        try {
            java.util.Set<java.nio.file.attribute.PosixFilePermission> ps =
                Files.getPosixFilePermissions(abs, LinkOption.NOFOLLOW_LINKS);
            return java.nio.file.attribute.PosixFilePermissions.toString(ps);
        } catch (Exception e) {
            try {
                Boolean ro = (Boolean) Files.getAttribute(abs, "dos:readonly", LinkOption.NOFOLLOW_LINKS);
                return Boolean.TRUE.equals(ro) ? "r--r--r--" : "rw-rw-rw-";
            } catch (Exception e2) {
                return "---";
            }
        }
    }

    /** 单条文件/目录信息（fs_stat 使用，对齐服务器 _entry_info，不跟随符号链接）。 */
    private static @NotNull Map<String, Object> statInfo(@NotNull String workspace, @NotNull Path abs) {
        Map<String, Object> info = new LinkedHashMap<>();
        try {
            BasicFileAttributes attrs = Files.readAttributes(abs, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            String name = abs.getFileName().toString();
            boolean isLink = attrs.isSymbolicLink();
            boolean isDir = attrs.isDirectory() && !isLink;
            long size = isDir ? 0 : attrs.size();
            info.put("name", name);
            info.put("path", toRel(workspace, abs));
            info.put("type", isLink ? "symlink" : (isDir ? "directory" : "file"));
            info.put("size", size);
            info.put("size_human", isDir ? "-" : fmtSize(size));
            info.put("modified", attrs.lastModifiedTime().toInstant().toString());
            info.put("created", attrs.creationTime().toInstant().toString());
            info.put("permissions", permissionsOf(abs));
            if (isLink) {
                try {
                    info.put("target", Files.readSymbolicLink(abs).toString());
                } catch (IOException ignored) {
                    info.put("target", null);
                }
            }
        } catch (IOException e) {
            info.put("name", abs.getFileName().toString());
            info.put("path", toRel(workspace, abs));
            info.put("type", "unknown");
        }
        return info;
    }

    /** 子串出现次数。 */
    private static int countOccurrences(@NotNull String s, @NotNull String sub) {
        if (sub.isEmpty()) return 0;
        int count = 0, idx = 0;
        while ((idx = s.indexOf(sub, idx)) != -1) {
            count++;
            idx += sub.length();
        }
        return count;
    }

    /** 递归复制目录（含符号链接本身）。 */
    private static void copyTree(@NotNull Path src, @NotNull Path dst) throws IOException {
        Files.createDirectories(dst);
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(src)) {
            for (Path e : ds) {
                Path childDst = dst.resolve(e.getFileName().toString());
                if (Files.isDirectory(e, LinkOption.NOFOLLOW_LINKS)) {
                    copyTree(e, childDst);
                } else if (Files.isSymbolicLink(e)) {
                    Files.createSymbolicLink(childDst, Files.readSymbolicLink(e));
                } else {
                    Files.copy(e, childDst, StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
    }

    /** 递归删除目录/文件（不跟随符号链接）。 */
    private static void deleteTree(@NotNull Path p) throws IOException {
        if (Files.isDirectory(p, LinkOption.NOFOLLOW_LINKS)) {
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(p)) {
                for (Path e : ds) deleteTree(e);
            }
            Files.deleteIfExists(p);
        } else {
            Files.deleteIfExists(p);
        }
    }

    /** 移动（跨文件系统退化为复制+删除，等价 shutil.move / mv 跨盘语义）。 */
    private static void movePath(@NotNull Path src, @NotNull Path dst) throws IOException {
        try {
            Files.move(src, dst);
        } catch (IOException e) {
            if (Files.isDirectory(src, LinkOption.NOFOLLOW_LINKS) && !Files.isSymbolicLink(src)) {
                copyTree(src, dst);
                deleteTree(src);
            } else {
                Files.copy(src, dst);
                Files.deleteIfExists(src);
            }
        }
    }

    /** 目标是否位于回收站目录内（禁止删除回收站本身/内部）。 */
    private static boolean isInsideTrashDir(@NotNull String workspace, @NotNull Path abs) {
        Path trashRoot = Paths.get(workspace).toAbsolutePath().normalize().resolve(TRASH_DIR_NAME);
        Path resolved = abs.toAbsolutePath().normalize();
        return resolved.equals(trashRoot) || resolved.startsWith(trashRoot);
    }

    /** 回收站会话目录：<workspace>/.agent-trash/<UTC时间戳>-<随机6位>。 */
    private static @NotNull Path newTrashSessionDir(@NotNull String workspace) {
        String stamp = java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")
            .withZone(java.time.ZoneOffset.UTC).format(java.time.Instant.now());
        String rand = UUID.randomUUID().toString().replace("-", "").substring(0, 6);
        return Paths.get(workspace).toAbsolutePath().normalize().resolve(TRASH_DIR_NAME).resolve(stamp + "-" + rand);
    }

    /** 把目标移入回收站（保留相对目录结构），返回回收站内绝对路径；失败返回 null。 */
    private static @Nullable Path trashMove(@NotNull String workspace, @NotNull Path absPath) {
        try {
            Path sessionDir = newTrashSessionDir(workspace);
            Files.createDirectories(sessionDir);
            String rel = toRel(workspace, absPath);
            Path dest = sessionDir.resolve(rel);
            Files.createDirectories(dest.getParent());
            movePath(absPath, dest);
            return dest;
        } catch (IOException e) {
            return null;
        }
    }

    /** fs_stat：获取文件/目录信息（不跟随符号链接）。 */
    private static @NotNull String fsStat(@NotNull String workspace, @NotNull JsonObject args) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("stat", "INVALID_PATH", "path 不能为空");
        Path target = resolveSafe(workspace, rel, true);
        if (target == null) return fail("stat", "INVALID_PATH", "非法路径（仅允许工作区相对路径）：" + rel, rel);
        if (!pathExists(target)) return fail("stat", "PATH_NOT_FOUND", "路径不存在：" + rel, rel);
        Map<String, Object> info = statInfo(workspace, target);
        info.remove("path");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "stat");
        out.put("path", toRel(workspace, target));
        out.putAll(info);
        return GSON.toJson(out);
    }

    /** fs_write：创建/覆盖文件（父目录自动创建；不承担局部修改）。 */
    private static @NotNull String fsWrite(@NotNull String workspace, @NotNull JsonObject args) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("write", "INVALID_PATH", "path 不能为空");
        String encoding = getString(args, "encoding", "utf-8");
        String content = getString(args, "content", "");
        Charset cs;
        try {
            cs = Charset.forName(encoding);
        } catch (Exception e) {
            return fail("write", "ENCODING_ERROR", "不支持的编码格式：" + encoding, rel);
        }
        byte[] data = content.getBytes(cs);
        if (data.length > MAX_FILE_SIZE) {
            return fail("write", "SIZE_LIMIT_EXCEEDED",
                "写入内容 " + fmtSize(data.length) + " 超过单文件上限 " + fmtSize(MAX_FILE_SIZE), rel);
        }
        Path target = resolveSafe(workspace, rel, true);
        if (target == null) return fail("write", "INVALID_PATH", "非法路径（仅允许工作区相对路径）：" + rel, rel);
        if (Files.exists(target) && Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS)) {
            return fail("write", "ALREADY_EXISTS", "'" + rel + "' 已存在且是目录", rel);
        }
        boolean created = !Files.exists(target);
        long size;
        try {
            Files.createDirectories(target.getParent());
            Files.write(target, data);
            size = Files.size(target);
        } catch (IOException e) {
            return fail("write", "OPERATION_FAILED", "写入失败：" + e.getMessage(), rel);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "write");
        out.put("path", toRel(workspace, target));
        out.put("bytes_written", data.length);
        out.put("chars_written", content.length());
        out.put("created", created);
        out.put("size", size);
        out.put("size_human", fmtSize(size));
        return GSON.toJson(out);
    }

    /** fs_edit：精确替换文件中的文本片段（多处命中仅替换第 1 处）。 */
    private static @NotNull String fsEdit(@NotNull String workspace, @NotNull JsonObject args) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("edit", "INVALID_PATH", "path 不能为空");
        String encoding = getString(args, "encoding", "utf-8");
        Path target = resolveSafe(workspace, rel, true);
        if (target == null) return fail("edit", "INVALID_PATH", "非法路径（仅允许工作区相对路径）：" + rel, rel);
        if (!pathExists(target)) return fail("edit", "PATH_NOT_FOUND", "路径不存在：" + rel, rel);
        if (Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS)) {
            return fail("edit", "IS_DIRECTORY", "'" + rel + "' 不是一个文件", rel);
        }
        Charset cs;
        try {
            cs = Charset.forName(encoding);
        } catch (Exception e) {
            return fail("edit", "ENCODING_ERROR", "不支持的编码格式：" + encoding, rel);
        }
        String content;
        try {
            content = Files.readString(target, cs);
        } catch (IOException e) {
            return fail("edit", "OPERATION_FAILED", "读取文件失败：" + e.getMessage(), rel);
        }
        String oldText = getString(args, "old_text", "");
        if (oldText.isEmpty()) return fail("edit", "INVALID_ARGUMENT", "old_text 不能为空", rel);
        int occurrences = countOccurrences(content, oldText);
        if (occurrences == 0) {
            return fail("edit", "TARGET_NOT_FOUND", "未找到目标文本（old_text），请先 fs_read 确认当前内容后再编辑", rel);
        }
        int idx = content.indexOf(oldText);
        int changedLine = content.substring(0, idx).split("\n", -1).length;
        String newText = getString(args, "new_text", "");
        String newContent = content.substring(0, idx) + newText + content.substring(idx + oldText.length());
        byte[] data = newContent.getBytes(cs);
        if (data.length > MAX_FILE_SIZE) {
            return fail("edit", "SIZE_LIMIT_EXCEEDED",
                "修改后文件 " + fmtSize(data.length) + " 超过单文件上限 " + fmtSize(MAX_FILE_SIZE), rel);
        }
        long size;
        try {
            Files.write(target, data);
            size = Files.size(target);
        } catch (IOException e) {
            return fail("edit", "OPERATION_FAILED", "写入失败：" + e.getMessage(), rel);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "edit");
        out.put("path", toRel(workspace, target));
        out.put("old_text_chars", oldText.length());
        out.put("new_text_chars", newText.length());
        out.put("replaced_count", 1);
        out.put("occurrences", occurrences);
        out.put("changed_line", changedLine);
        out.put("bytes_written", data.length);
        out.put("size", size);
        out.put("size_human", fmtSize(size));
        if (occurrences > 1) {
            out.put("warning", "目标文本出现 " + occurrences + " 次，本次仅替换第 1 处（第 " + changedLine + " 行）");
        }
        return GSON.toJson(out);
    }

    /** fs_mkdir：创建目录（mkdir -p 语义，已存在目录幂等成功）。 */
    private static @NotNull String fsMkdir(@NotNull String workspace, @NotNull JsonObject args) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("mkdir", "INVALID_PATH", "path 不能为空");
        Path target = resolveSafe(workspace, rel, true);
        if (target == null) return fail("mkdir", "INVALID_PATH", "非法路径（仅允许工作区相对路径）：" + rel, rel);
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS) && !Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS)) {
            return fail("mkdir", "ALREADY_EXISTS", "'" + rel + "' 已存在且是文件，无法创建同名目录", rel);
        }
        boolean existed = Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS);
        if (!existed) {
            try {
                Files.createDirectories(target);
            } catch (IOException e) {
                return fail("mkdir", "OPERATION_FAILED", "创建目录失败：" + e.getMessage(), rel);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "mkdir");
        out.put("path", toRel(workspace, target));
        out.put("created", !existed);
        out.put("existed", existed);
        return GSON.toJson(out);
    }

    /** fs_copy：复制文件或目录（目标存在时需 overwrite=true）。 */
    private static @NotNull String fsCopy(@NotNull String workspace, @NotNull JsonObject args) {
        String src = getString(args, "src", "");
        String dst = getString(args, "dst", "");
        if (src.isBlank() || dst.isBlank()) return fail("copy", "INVALID_PATH", "src/dst 不能为空");
        Path srcAbs = resolveSafe(workspace, src, true);
        if (srcAbs == null) return fail("copy", "INVALID_PATH", "非法源路径：" + src, src);
        if (srcAbs.toAbsolutePath().normalize().equals(Paths.get(workspace).toAbsolutePath().normalize())) {
            return fail("copy", "RISK_BLOCKED", "禁止复制工作区根目录本身", src);
        }
        if (!pathExists(srcAbs)) return fail("copy", "PATH_NOT_FOUND", "源路径不存在：" + src, src);
        Path dstAbs = resolveSafe(workspace, dst, true);
        if (dstAbs == null) return fail("copy", "INVALID_PATH", "非法目标路径：" + dst, dst);
        if (srcAbs.equals(dstAbs)) return fail("copy", "INVALID_ARGUMENT", "源路径与目标路径相同", src);
        boolean overwrite = args.has("overwrite") && args.get("overwrite").getAsBoolean();
        if (pathExists(dstAbs) && !overwrite) {
            return fail("copy", "ALREADY_EXISTS", "目标已存在：" + dst + "；如需覆盖请设置 overwrite=true", dst);
        }
        try {
            Files.createDirectories(dstAbs.getParent());
            boolean isDir = Files.isDirectory(srcAbs, LinkOption.NOFOLLOW_LINKS) && !Files.isSymbolicLink(srcAbs);
            if (isDir) {
                if (pathExists(dstAbs)) deleteTree(dstAbs);
                copyTree(srcAbs, dstAbs);
                int itemCount = countAllEntries(dstAbs);
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("success", true);
                out.put("operation", "copy");
                out.put("src", toRel(workspace, srcAbs));
                out.put("dst", toRel(workspace, dstAbs));
                out.put("kind", "directory");
                out.put("item_count", itemCount);
                return GSON.toJson(out);
            } else {
                if (pathExists(dstAbs)) Files.delete(dstAbs);
                Files.copy(srcAbs, dstAbs, LinkOption.NOFOLLOW_LINKS);
                long size = Files.size(dstAbs);
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("success", true);
                out.put("operation", "copy");
                out.put("src", toRel(workspace, srcAbs));
                out.put("dst", toRel(workspace, dstAbs));
                out.put("kind", "file");
                out.put("bytes_copied", size);
                out.put("size_human", fmtSize(size));
                return GSON.toJson(out);
            }
        } catch (IOException e) {
            return fail("copy", "OPERATION_FAILED", "复制失败：" + e.getMessage(), src);
        }
    }

    /** fs_move：移动/重命名文件或目录（父目录自动创建；对符号链接移动链接本身）。 */
    private static @NotNull String fsMove(@NotNull String workspace, @NotNull JsonObject args) {
        String src = getString(args, "src", "");
        String dst = getString(args, "dst", "");
        if (src.isBlank() || dst.isBlank()) return fail("move", "INVALID_PATH", "src/dst 不能为空");
        Path srcAbs = resolveSafe(workspace, src, false); // follow_final=False：移动链接本身
        if (srcAbs == null) return fail("move", "INVALID_PATH", "非法源路径：" + src, src);
        if (srcAbs.toAbsolutePath().normalize().equals(Paths.get(workspace).toAbsolutePath().normalize())) {
            return fail("move", "RISK_BLOCKED", "禁止移动工作区根目录本身", src);
        }
        if (!pathExists(srcAbs)) return fail("move", "PATH_NOT_FOUND", "源路径不存在：" + src, src);
        Path dstAbs = resolveSafe(workspace, dst, true);
        if (dstAbs == null) return fail("move", "INVALID_PATH", "非法目标路径：" + dst, dst);
        if (srcAbs.equals(dstAbs)) return fail("move", "INVALID_ARGUMENT", "源路径与目标路径相同", src);
        if (pathExists(dstAbs)) return fail("move", "ALREADY_EXISTS", "目标已存在：" + dst, dst);
        try {
            Files.createDirectories(dstAbs.getParent());
            movePath(srcAbs, dstAbs);
        } catch (IOException e) {
            return fail("move", "OPERATION_FAILED", "移动失败：" + e.getMessage(), src);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "move");
        out.put("src", toRel(workspace, srcAbs));
        out.put("dst", toRel(workspace, dstAbs));
        return GSON.toJson(out);
    }

    /** fs_delete：删除文件/目录（一律进回收站 .agent-trash，可恢复；非空目录需 recursive=true）。 */
    private static @NotNull String fsDelete(@NotNull String workspace, @NotNull JsonObject args) {
        String rel = getString(args, "path", "");
        if (rel.isBlank()) return fail("delete", "INVALID_PATH", "path 不能为空");
        Path target = resolveSafe(workspace, rel, false);
        if (target == null) return fail("delete", "INVALID_PATH", "非法路径（仅允许工作区相对路径）：" + rel, rel);
        if (!pathExists(target)) return fail("delete", "PATH_NOT_FOUND", "路径不存在", rel);
        // 风险控制：禁止删工作区根目录本身；禁止删除回收站内部
        Path base = Paths.get(workspace).toAbsolutePath().normalize();
        if (target.toAbsolutePath().normalize().equals(base)) {
            return fail("delete", "RISK_BLOCKED", "禁止删除工作区根目录本身", rel);
        }
        if (isInsideTrashDir(workspace, target)) {
            return fail("delete", "RISK_BLOCKED", "禁止删除回收站等工具包内部目录", rel);
        }
        boolean recursive = args.has("recursive") && args.get("recursive").getAsBoolean();
        if (Files.isDirectory(target, LinkOption.NOFOLLOW_LINKS) && !Files.isSymbolicLink(target)) {
            boolean isEmpty;
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(target)) {
                isEmpty = !ds.iterator().hasNext();
            } catch (IOException e) {
                isEmpty = false;
            }
            if (!isEmpty && !recursive) {
                return fail("delete", "NOT_EMPTY",
                    "目录非空，无法直接删除；如需递归删除整个目录树请将 recursive 设为 true（删除会进入回收站）", rel);
            }
        }
        Path trashDest = trashMove(workspace, target);
        if (trashDest == null) return fail("delete", "OPERATION_FAILED", "移入回收站失败", rel);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", true);
        out.put("operation", "delete");
        out.put("path", toRel(workspace, target));
        out.put("trashed", true);
        out.put("trash_path", toRel(workspace, trashDest));
        out.put("recoverable", true);
        out.put("restore_hint", "文件已进入回收站 .agent-trash/，可手工移回原路径恢复（V2 将提供 fs_restore）");
        return GSON.toJson(out);
    }

    // ===== PathGuard =====

    /** 把相对工作区根路径解析为绝对路径，并确保仍落在工作区内（拒绝 .. 逃逸/绝对路径/符号链接逃逸）。 */
    private static @Nullable Path resolveSafe(@NotNull String workspace, @NotNull String rel) {
        return resolveSafe(workspace, rel, true);
    }

    /**
     * followFinal=false（删除/移动）：只解析父目录，最后一段保持原样，保证"操作的是链接本身"、
     * 而不是链接指向的目标（等价服务器 PathGuard.resolve(follow_final=False)）。
     */
    private static @Nullable Path resolveSafe(@NotNull String workspace, @NotNull String rel, boolean followFinal) {
        if (rel == null || rel.isBlank()) return null;
        if (rel.indexOf('\0') >= 0) return null; // 拒绝 NUL（对齐服务器 PathGuard）
        Path base = Paths.get(workspace).toAbsolutePath().normalize();
        // 绝对路径 / 盘符 / UNC 一律拒绝
        if (rel.startsWith("\\\\") || rel.matches("(?i)^[a-z]:.*")) return null;
        Path p = Paths.get(rel);
        if (p.isAbsolute()) return null;
        for (Path seg : p) {
            if ("..".equals(seg.toString())) return null;
        }
        String normalized = rel.replace("\\", "/");
        if (!followFinal) {
            // '.' 整体解析为工作区根：交还调用方判定（删除根会被风险层拦截，返回 RISK_BLOCKED）
            if (".".equals(normalized)) return base;
            int idx = normalized.lastIndexOf('/');
            String parentRel = idx >= 0 ? normalized.substring(0, idx) : "";
            String name = idx >= 0 ? normalized.substring(idx + 1) : normalized;
            if (name.isBlank() || "..".equals(name) || ".".equals(name)) return null;
            Path parent = resolveSafe(workspace, parentRel.isEmpty() ? "." : parentRel, true);
            if (parent == null) return null;
            Path candidate = parent.resolve(name).normalize();
            if (!candidate.startsWith(base)) return null;
            return candidate;
        }
        Path candidate = base.resolve(p).normalize();
        if (!candidate.startsWith(base)) return null;
        // 符号链接逃逸：真实路径必须在工作区内（realpathLenient 处理"末段尚不存在"的写入目标）
        try {
            Path realBase = base.toRealPath();
            Path real = realpathLenient(candidate);
            if (!real.startsWith(realBase)) return null;
            return real;
        } catch (IOException e) {
            // 路径不存在：仍在工作区内的 candidate 返回，供上层判定 NOT_FOUND
            return candidate;
        }
    }

    /**
     * 宽松 realpath：解析到"最深已存在祖先"的真实路径后，再补回尚不存在的末段。
     * 用于写入/创建目标（末段可能不存在）时仍能捕捉"父级符号链接逃逸"。
     */
    private static @NotNull Path realpathLenient(@NotNull Path p) throws IOException {
        Path cur = p.toAbsolutePath().normalize();
        List<Path> rest = new ArrayList<>();
        while (!Files.exists(cur) && cur.getParent() != null) {
            rest.add(0, cur.getFileName());
            cur = cur.getParent();
        }
        Path resolved = cur.toRealPath();
        for (Path seg : rest) resolved = resolved.resolve(seg);
        return resolved;
    }

    /** 存在的判断（含"断开的符号链接"也算存在，align 服务器 must_exist 的 is_symlink()）。 */
    private static boolean pathExists(@NotNull Path p) {
        return Files.exists(p) || Files.isSymbolicLink(p);
    }

    /** 递归统计目录下条目数（含子目录内，不含自身）。 */
    private static int countAllEntries(@NotNull Path dir) throws IOException {
        int n = 0;
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir)) {
            for (Path e : ds) {
                n++;
                if (Files.isDirectory(e, LinkOption.NOFOLLOW_LINKS)) n += countAllEntries(e);
            }
        }
        return n;
    }

    /** 判断单个目录项/文件名是否需要排除（大小写不敏感）。 */
    private static boolean isSkippedName(@NotNull String name, @NotNull java.util.Set<String> dirs) {
        return dirs.contains(name.toLowerCase(Locale.ROOT));
    }

    /** 判断文件扩展名是否为生成的二进制/编译产物。 */
    private static boolean isSkippedFileExtension(@NotNull String rel, @NotNull java.util.Set<String> fileExts) {
        int idx = rel.lastIndexOf('.');
        if (idx < 0) return false;
        String ext = rel.substring(idx).toLowerCase(Locale.ROOT);
        return ext.length() > 1 && fileExts.contains(ext);
    }

    /** 相对路径是否落在被排除的依赖/产物目录内（任一段命中即排除）。 */
    private static boolean isInsideSkipped(@NotNull String rel, @NotNull java.util.Set<String> dirs) {
        if (rel == null || rel.isBlank() || ".".equals(rel)) return false;
        if (rel.startsWith("\\\\") || rel.matches("(?i)^[a-z]:.*") || rel.startsWith("/")) return false;
        String normalized = rel.replace("\\", "/").replaceFirst("^\\./", "").replaceFirst("^/+", "");
        if (normalized.isBlank() || ".".equals(normalized)) return false;
        for (String seg : normalized.split("/")) {
            if (seg.isBlank()) continue;
            if (isSkippedName(seg, dirs)) return true;
        }
        return false;
    }

    private static boolean globMatches(@NotNull String name, @NotNull String pattern) {
        // 简化 glob：* → .* ，? → . 后整串匹配（不处理 [] / ** 复杂语义，够用）
        StringBuilder rx = new StringBuilder("^");
        for (char c : pattern.toCharArray()) {
            if (c == '*') rx.append(".*");
            else if (c == '?') rx.append('.');
            else if ("\\.^$|()[]{}+".indexOf(c) >= 0) rx.append('\\').append(c);
            else rx.append(c);
        }
        rx.append('$');
        return Pattern.compile(rx.toString(), Pattern.CASE_INSENSITIVE).matcher(name).matches();
    }

    private static @NotNull Map<String, Object> entryInfo(@NotNull String workspace, @NotNull Path abs) {
        Map<String, Object> info = new LinkedHashMap<>();
        try {
            BasicFileAttributes attrs = Files.readAttributes(abs, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            String name = abs.getFileName().toString();
            boolean isLink = attrs.isSymbolicLink();
            boolean isDir = attrs.isDirectory() && !isLink;
            info.put("name", name);
            info.put("path", toRel(workspace, abs));
            info.put("type", isLink ? "symlink" : (isDir ? "directory" : "file"));
            info.put("size", isDir ? 0 : attrs.size());
            if (isLink) {
                try {
                    info.put("target", Files.readSymbolicLink(abs).toString());
                } catch (IOException ignored) {
                    // ignore
                }
            }
        } catch (IOException e) {
            info.put("name", abs.getFileName().toString());
            info.put("path", toRel(workspace, abs));
            info.put("type", "unknown");
        }
        return info;
    }

    private static @NotNull String toRel(@NotNull String workspace, @NotNull Path abs) {
        Path base = Paths.get(workspace).toAbsolutePath().normalize();
        String rel = base.relativize(abs.toAbsolutePath().normalize()).toString().replace("\\", "/");
        return rel.isEmpty() ? "." : rel;
    }

    private static @NotNull String fail(@NotNull String operation, @NotNull String code, @NotNull String message) {
        return fail(operation, code, message, null);
    }

    private static @NotNull String fail(@NotNull String operation, @NotNull String code,
                                        @NotNull String message, @Nullable String path) {
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("code", code);
        err.put("message", message);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", false);
        out.put("operation", operation);
        out.put("error", err);
        if (path != null) out.put("path", path);
        return GSON.toJson(out);
    }

    @NotNull
    private static String getString(@NotNull JsonObject obj, @NotNull String key, @NotNull String def) {
        if (obj.has(key) && obj.get(key).isJsonPrimitive()) {
            return obj.get(key).getAsString();
        }
        return def;
    }
}
