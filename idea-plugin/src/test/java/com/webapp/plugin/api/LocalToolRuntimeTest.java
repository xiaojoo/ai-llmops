package com.webapp.plugin.api;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class LocalToolRuntimeTest {

    @TempDir
    Path ws;

    private JsonObject parse(String json) {
        return JsonParser.parseString(json).getAsJsonObject();
    }

    @Test
    void fsReadReadsInsideWorkspace() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.writeString(ws.resolve("src/App.vue"), "line1\nline2\nline3\n");
        JsonObject in = new JsonObject();
        in.addProperty("path", "src/App.vue");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals("read", res.get("operation").getAsString());
        assertEquals("line1\nline2\nline3", res.get("content").getAsString());
    }

    @Test
    void fsReadRejectsTraversal() {
        JsonObject in = new JsonObject();
        in.addProperty("path", "../secret.txt");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("INVALID_PATH", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsReadRejectsAbsolutePath() {
        JsonObject in = new JsonObject();
        in.addProperty("path", "C:/Users/x/secret.txt");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", in));
        assertEquals(false, res.get("success").getAsBoolean());
    }

    @Test
    void fsListListsEntriesWithDirectoriesFirst() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.createDirectories(ws.resolve("docs"));
        Files.writeString(ws.resolve("a.txt"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("path", ".");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_list", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(3, res.get("entries").getAsJsonArray().size());
        assertEquals("directory", res.get("entries").getAsJsonArray().get(0).getAsJsonObject().get("type").getAsString());
    }

    @Test
    void fsSearchFindsByPattern() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.writeString(ws.resolve("src/a.py"), "x");
        Files.writeString(ws.resolve("src/b.md"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("pattern", "*.py");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_search", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(1, res.get("total_found").getAsInt());
        assertEquals("src/a.py", res.get("matches").getAsJsonArray().get(0).getAsJsonObject().get("path").getAsString());
    }

    @Test
    void unsupportedToolReported() {
        JsonObject in = new JsonObject();
        in.addProperty("command", "rm");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "shell_run", in));
        assertFalse(res.get("success").getAsBoolean());
        assertEquals("UNSUPPORTED", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void noWorkspaceFailsSafely() {
        JsonObject in = new JsonObject();
        in.addProperty("path", "a.txt");
        JsonObject res = parse(LocalToolRuntime.execute("", "fs_read", in));
        assertFalse(res.get("success").getAsBoolean());
        assertEquals("NO_WORKSPACE", res.getAsJsonObject("error").get("code").getAsString());
    }

    // ===== 默认排除依赖/产物目录（只读源码） =====

    @Test
    void fsListExcludesDependencyDirs() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.createDirectories(ws.resolve("venv"));
        Files.createDirectories(ws.resolve("node_modules"));
        Files.createDirectories(ws.resolve("dist"));
        Files.writeString(ws.resolve("a.py"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("path", ".");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_list", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(2, res.get("entries").getAsJsonArray().size()); // src + a.py
    }

    @Test
    void fsReadRejectsInsideSkippedDir() throws IOException {
        Files.createDirectories(ws.resolve("venv/lib"));
        Files.writeString(ws.resolve("venv/lib/x.py"), "secret");
        JsonObject in = new JsonObject();
        in.addProperty("path", "venv/lib/x.py");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("SKIPPED", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsReadRejectsGeneratedExtension() throws IOException {
        Files.writeString(ws.resolve("app.pyc"), "bin");
        JsonObject in = new JsonObject();
        in.addProperty("path", "app.pyc");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("SKIPPED", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsSearchPrunesSkippedDirs() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.createDirectories(ws.resolve("node_modules"));
        Files.writeString(ws.resolve("src/a.py"), "x");
        Files.writeString(ws.resolve("node_modules/dep.py"), "x");
        Files.writeString(ws.resolve("src/b.pyc"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("pattern", "*.py");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_search", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(1, res.get("matches").getAsJsonArray().size());
        assertEquals("src/a.py", res.get("matches").getAsJsonArray().get(0).getAsJsonObject().get("path").getAsString());
    }

    // ===== .webapp/ignore.json 自定义排除（只增不减） =====

    @Test
    void workspaceIgnoreJsonAddsCustomExcludes() throws IOException {
        Files.createDirectories(ws.resolve(".webapp"));
        Files.createDirectories(ws.resolve("custom_dir"));
        Files.writeString(ws.resolve("a.py"), "x");
        Files.writeString(ws.resolve("b.bundle"), "x");
        Files.writeString(ws.resolve(".webapp/ignore.json"),
            "{\"ignore_dirs\":[\"custom_dir\"],\"ignore_extensions\":[\".bundle\"]}");

        // 自定义目录不出现在 fs_list 结果
        JsonObject list = new JsonObject();
        list.addProperty("path", ".");
        JsonObject listRes = parse(LocalToolRuntime.execute(ws.toString(), "fs_list", list));
        assertEquals(true, listRes.get("success").getAsBoolean());
        String names = listRes.get("entries").getAsJsonArray().toString();
        assertFalse(names.contains("custom_dir"));

        // 自定义扩展名被 fs_read 拒绝
        JsonObject read = new JsonObject();
        read.addProperty("path", "b.bundle");
        JsonObject readRes = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", read));
        assertEquals(false, readRes.get("success").getAsBoolean());
        assertEquals("SKIPPED", readRes.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void loadWorkspaceSkipConfigFallsBackToBuiltin() throws IOException {
        // 无 .webapp/ignore.json 时内置排除仍生效：node_modules 被排除
        Files.createDirectories(ws.resolve("node_modules"));
        Files.writeString(ws.resolve("node_modules/x.py"), "x");
        JsonObject read = new JsonObject();
        read.addProperty("path", "node_modules/x.py");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_read", read));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("SKIPPED", res.getAsJsonObject("error").get("code").getAsString());
    }

    // ===== 写类工具（fs_stat/fs_write/fs_edit/fs_mkdir/fs_copy/fs_move/fs_delete） =====

    @Test
    void fsWriteCreatesAndOverwrites() throws IOException {
        JsonObject in = new JsonObject();
        in.addProperty("path", "src/main.py");
        in.addProperty("content", "print(1)\n");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_write", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals("write", res.get("operation").getAsString());
        assertEquals(true, res.get("created").getAsBoolean());
        assertEquals("print(1)\n", Files.readString(ws.resolve("src/main.py")));

        JsonObject in2 = new JsonObject();
        in2.addProperty("path", "src/main.py");
        in2.addProperty("content", "print(2)\n");
        JsonObject res2 = parse(LocalToolRuntime.execute(ws.toString(), "fs_write", in2));
        assertEquals(true, res2.get("success").getAsBoolean());
        assertEquals(false, res2.get("created").getAsBoolean());
        assertEquals("print(2)\n", Files.readString(ws.resolve("src/main.py")));
    }

    @Test
    void fsWriteRejectsTraversal() {
        JsonObject in = new JsonObject();
        in.addProperty("path", "../out.txt");
        in.addProperty("content", "x");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_write", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("INVALID_PATH", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsEditReplacesFirstOccurrence() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "x=1\ny=2\nx=1\n");
        JsonObject in = new JsonObject();
        in.addProperty("path", "a.txt");
        in.addProperty("old_text", "x=1");
        in.addProperty("new_text", "x=9");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_edit", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(2, res.get("occurrences").getAsInt());
        assertEquals(1, res.get("replaced_count").getAsInt());
        assertEquals(1, res.get("changed_line").getAsInt());
        assertEquals(true, res.has("warning"));
        assertEquals("x=9\ny=2\nx=1\n", Files.readString(ws.resolve("a.txt")));
    }

    @Test
    void fsEditTargetNotFound() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "hello");
        JsonObject in = new JsonObject();
        in.addProperty("path", "a.txt");
        in.addProperty("old_text", "nope");
        in.addProperty("new_text", "x");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_edit", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("TARGET_NOT_FOUND", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsMkdirCreatesNestedAndIdempotent() throws IOException {
        JsonObject in = new JsonObject();
        in.addProperty("path", "a/b/c");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_mkdir", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(false, res.get("existed").getAsBoolean());
        assertEquals(true, Files.isDirectory(ws.resolve("a/b/c")));

        JsonObject res2 = parse(LocalToolRuntime.execute(ws.toString(), "fs_mkdir", in));
        assertEquals(true, res2.get("success").getAsBoolean());
        assertEquals(true, res2.get("existed").getAsBoolean());
    }

    @Test
    void fsCopyCopiesFileAndRespectsOverwrite() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "data");
        JsonObject in1 = new JsonObject();
        in1.addProperty("src", "a.txt");
        in1.addProperty("dst", "b.txt");
        JsonObject res1 = parse(LocalToolRuntime.execute(ws.toString(), "fs_copy", in1));
        assertEquals(true, res1.get("success").getAsBoolean());
        assertEquals("file", res1.get("kind").getAsString());
        assertEquals("data", Files.readString(ws.resolve("b.txt")));

        JsonObject res2 = parse(LocalToolRuntime.execute(ws.toString(), "fs_copy", in1));
        assertEquals(false, res2.get("success").getAsBoolean());
        assertEquals("ALREADY_EXISTS", res2.getAsJsonObject("error").get("code").getAsString());

        JsonObject in3 = new JsonObject();
        in3.addProperty("src", "a.txt");
        in3.addProperty("dst", "b.txt");
        in3.addProperty("overwrite", true);
        JsonObject res3 = parse(LocalToolRuntime.execute(ws.toString(), "fs_copy", in3));
        assertEquals(true, res3.get("success").getAsBoolean());
    }

    @Test
    void fsCopyCopiesDirectory() throws IOException {
        Files.createDirectories(ws.resolve("src/sub"));
        Files.writeString(ws.resolve("src/a.py"), "x");
        Files.writeString(ws.resolve("src/sub/b.py"), "y");
        JsonObject in = new JsonObject();
        in.addProperty("src", "src");
        in.addProperty("dst", "dst");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_copy", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals("directory", res.get("kind").getAsString());
        assertEquals(true, Files.exists(ws.resolve("dst/sub/b.py")));
    }

    @Test
    void fsMoveMovesAndCreatesParent() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "data");
        JsonObject in = new JsonObject();
        in.addProperty("src", "a.txt");
        in.addProperty("dst", "x/y/b.txt");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_move", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals(false, Files.exists(ws.resolve("a.txt")));
        assertEquals("data", Files.readString(ws.resolve("x/y/b.txt")));
    }

    @Test
    void fsMoveTargetExistsReportsAlreadyExists() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "data");
        Files.writeString(ws.resolve("b.txt"), "exist");
        JsonObject in = new JsonObject();
        in.addProperty("src", "a.txt");
        in.addProperty("dst", "b.txt");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_move", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("ALREADY_EXISTS", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsDeleteMovesToTrash() throws IOException {
        Files.writeString(ws.resolve("a.txt"), "secret");
        JsonObject in = new JsonObject();
        in.addProperty("path", "a.txt");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_delete", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals("delete", res.get("operation").getAsString());
        assertEquals(true, res.get("trashed").getAsBoolean());
        assertEquals(true, res.get("recoverable").getAsBoolean());
        assertEquals(false, Files.exists(ws.resolve("a.txt")));
        assertEquals(true, Files.exists(ws.resolve(".agent-trash")));
    }

    @Test
    void fsDeleteNonEmptyDirRequiresRecursive() throws IOException {
        Files.createDirectories(ws.resolve("d"));
        Files.writeString(ws.resolve("d/keep.txt"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("path", "d");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_delete", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("NOT_EMPTY", res.getAsJsonObject("error").get("code").getAsString());

        JsonObject in2 = new JsonObject();
        in2.addProperty("path", "d");
        in2.addProperty("recursive", true);
        JsonObject res2 = parse(LocalToolRuntime.execute(ws.toString(), "fs_delete", in2));
        assertEquals(true, res2.get("success").getAsBoolean());
        assertEquals(false, Files.exists(ws.resolve("d")));
    }

    @Test
    void fsDeleteRootBlocked() {
        JsonObject in = new JsonObject();
        in.addProperty("path", ".");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_delete", in));
        assertEquals(false, res.get("success").getAsBoolean());
        assertEquals("RISK_BLOCKED", res.getAsJsonObject("error").get("code").getAsString());
    }

    @Test
    void fsStatReturnsInfo() throws IOException {
        Files.createDirectories(ws.resolve("src"));
        Files.writeString(ws.resolve("src/a.py"), "x");
        JsonObject in = new JsonObject();
        in.addProperty("path", "src/a.py");
        JsonObject res = parse(LocalToolRuntime.execute(ws.toString(), "fs_stat", in));
        assertEquals(true, res.get("success").getAsBoolean());
        assertEquals("stat", res.get("operation").getAsString());
        assertEquals("src/a.py", res.get("path").getAsString());
        assertEquals("file", res.get("type").getAsString());
        assertEquals(1, res.get("size").getAsInt());
        assertEquals(true, res.has("modified"));
    }
}
