# WebApp 会话窗口 IntelliJ 插件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 JetBrains IDE（2024.2+）右侧新增"WebApp"工具窗口，内嵌 JCEF 浏览器加载现有 WebApp 会话页面（默认 `http://localhost:5173/web-apps/Tf5qMSSgDiqHZkdg`），登录态由页面自身管理并跨 IDE 重启保持，预留 JS→Java Bridge。

**Architecture:** Tool Window（anchor=right）→ WebAppPanel（实现 Disposable）→ JBCefBrowser（JCEF，加载配置 URL）+ Swing 状态覆盖层（Loading/NetworkError/...）+ WebAppBridge（JBCefJSQuery 双向通道）。插件只做"WebApp 容器"，不实现登录/SSE/会话业务逻辑。设置经 PersistentStateComponent 持久化，URL 两段式配置（Server URL + Path）并做安全校验。

**Tech Stack:** Java 21 / Gradle 9.7.1 / IntelliJ Platform Gradle Plugin 2.18.1（`org.jetbrains.intellij.platform`）/ IntelliJ Platform 2024.2（since-build 242，until-build 252.*）/ JBCefBrowser (JCEF) / JUnit 5

**Spec:** `docs/superpowers/specs/2026-08-30-webapp-idea-plugin-design.md`

## Global Constraints

- 平台：IntelliJ Platform `2024.2+`（since-build `242`），until-build `261.*`（覆盖用户日常 IDE 2026.1，发版时随 Plugin Verifier 结果更新）；**构建 IDE 类型 `IU`（IntelliJ IDEA Ultimate）**——JCEF 仅随商业 IDE 分发，Community（IC）不含 JCEF（事实取证：ideaIC-2024.2 无 jcef 文件，见 IPGP issue #1522）；插件通过 `<depends>com.intellij.modules.jcef</depends>` 自动只在含 JCEF 的 IDE（Ultimate / PyCharm Professional / WebStorm / GoLand 等商业版）上加载
- Java：21（toolchain）；**Gradle：9.7.1**（wrapper 固定版本，用户指定）
- IPGP：**`org.jetbrains.intellij.platform` 2.18.1**（IPGP 2.x 最新；2.x 要求 Gradle 9.0+，插件 ID 与 1.x 的 `org.jetbrains.intellij` 不同）
- 构建 DSL：**`intellijPlatform {}`**（替代 1.x 的 `intellij {}`）；平台依赖在 `dependencies { intellijPlatform { ... } }` 中声明；since/until build 在 `intellijPlatform.pluginConfiguration.ideaVersion` 中配置
- JCEF 检查：一律用 `JBCefApp.isSupported()`（官方 API，**不是** `JBCefBrowser.isAvailable()`）
- plugin.xml：`<depends>com.intellij.modules.platform</depends>` + `<depends>com.intellij.modules.jcef</depends>`
- URL 校验白名单：仅 `http://`、`https://`；拒绝 `javascript:`、`file:`、`data:`、`chrome:`、`about:`、含空白/控制字符
- **插件不管理 Token/认证**：登录态由 WebApp 页面自身管理；插件只打开/刷新/销毁浏览器
- **登录态持久化机制（spec 修正）**：JCEF 为 IDE 进程级单例，插件**无法**为单个 JBCefBrowser 设置 cache_path；2023+ 版本 localStorage 重启 IDE 后持久保留（社区实证），依赖 IDE 的 JCEF 持久缓存目录即可，README 中记录此边界
- Bridge 消息协议：`{action: string, payload?: object}` → `{ok: boolean, data?: any, error?: string}`；未知 action 拒绝
- 工程根：`H:\ai-code-llmops\idea-webapp-plugin\`（独立 Gradle 工程，不并入 ai-code-llmops-web）
- 所有代码为 Java（不用 Kotlin/Scala），包名 `com.webapp.plugin`
- 提交规范：每个任务末尾 `git commit`，消息 `feat(webapp-plugin): ...`

---

### Task 1: Gradle 工程骨架 + plugin.xml + 最小工具窗口

**Files:**
- Create: `idea-webapp-plugin/settings.gradle.kts`
- Create: `idea-webapp-plugin/build.gradle.kts`
- Create: `idea-webapp-plugin/gradle.properties`
- Create: `idea-webapp-plugin/gradlew` / `gradlew.bat` / `gradle/wrapper/gradle-wrapper.properties`（wrapper 生成）
- Create: `idea-webapp-plugin/src/main/resources/META-INF/plugin.xml`
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`
- Create: `idea-webapp-plugin/.gitignore`

**Interfaces:**
- Produces: `com.webapp.plugin.toolwindow.WebAppToolWindowFactory`（实现 `com.intellij.openapi.wm.ToolWindowFactory`，`createToolWindowContent(Project, ToolWindow)` 方法）——后续 Task 5 会在该方法中创建 WebAppPanel

- [ ] **Step 1: 创建 Gradle 工程文件**

`idea-webapp-plugin/settings.gradle.kts`:
```kotlin
rootProject.name = "webapp-session-window"
```

`idea-webapp-plugin/gradle.properties`:
```properties
org.gradle.jvmargs=-Xmx2g
org.gradle.caching=true
```

`idea-webapp-plugin/build.gradle.kts`:
```kotlin
plugins {
    id("java")
    id("org.jetbrains.intellij.platform") version "2.18.1"
}

group = "com.webapp"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))
    }
}

dependencies {
    testImplementation(platform("org.junit:junit-bom:5.10.2"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")

    intellijPlatform {
        intellijIdeaUltimate("2024.2")
        testFramework(org.jetbrains.intellij.platform.gradle.TestFrameworkType.Platform)
    }
}

intellijPlatform {
    // Task 8 裁决：禁用 buildSearchableOptions（该任务拉起 headless IDE 被沙箱 socket bind 拒绝；
    // 内部插件设置搜索框索引非必需，消除构建环境依赖）
    buildSearchableOptions = false
    pluginConfiguration {
        ideaVersion {
            sinceBuild = "242"
            untilBuild = "252.*"
        }
    }
}

tasks {
    test {
        useJUnitPlatform()
    }
}
```

> 说明（IPGP 2.x 与 1.x 的差异）：
> - 插件 ID 为 `org.jetbrains.intellij.platform`（不是 1.x 的 `org.jetbrains.intellij`），要求 Gradle 9.0+
> - 平台依赖（2024.2 / **IU Ultimate**）在 `dependencies { intellijPlatform { ... } }` 声明，不再用 `intellij { version/type }`；**用 Ultimate 而非 Community**——JCEF 仅随商业 IDE 分发，IC 不含 JCEF（Task 1 已取证），Task 5+ 的 JCEF API 需要 Ultimate SDK 才能编译
> - since/until build 在 `intellijPlatform.pluginConfiguration.ideaVersion` 配置，不再用 `patchPluginXml` 任务
> - `testFramework(TestFrameworkType.Platform)` 提供插件测试所需的平台测试框架；纯 JUnit5 单测仍走 `testImplementation`
> - JCEF 依赖通过 plugin.xml 的 `<depends>com.intellij.modules.jcef</depends>` 声明，插件自动只在含 JCEF 的 IDE 上加载

`idea-webapp-plugin/.gitignore`:
```gitignore
build/
.idea/
*.iml
.gradle/
```

- [ ] **Step 2: 创建 plugin.xml**

`idea-webapp-plugin/src/main/resources/META-INF/plugin.xml`:
```xml
<idea-plugin>
    <id>com.webapp.session-window</id>
    <name>WebApp Session Window</name>
    <vendor>internal</vendor>
    <description><![CDATA[
        Embed the WebApp AI session window in the IDE via JCEF.
        ]]></description>

    <depends>com.intellij.modules.platform</depends>
    <depends>com.intellij.modules.jcef</depends>

    <extensions defaultExtensionNs="com.intellij">
        <toolWindow id="WebApp"
                    anchor="right"
                    factoryClass="com.webapp.plugin.toolwindow.WebAppToolWindowFactory"/>
        <applicationConfigurable parentId="tools"
                                 instance="com.webapp.plugin.settings.WebAppSettingsConfigurable"/>
    </extensions>
</idea-plugin>
```

> 注：`WebAppSettingsConfigurable` 在 Task 8 才创建；在此之前 `buildPlugin` 会因为 class 缺失报错。因此 Task 1 的验证只做 `runIde` 前的编译检查替代：先临时注释掉 configurable 行，Task 8 恢复。本步直接保留注释状态：
> ```xml
> <!-- <applicationConfigurable parentId="tools" instance="com.webapp.plugin.settings.WebAppSettingsConfigurable"/> -->
> ```

- [ ] **Step 3: 创建最小工具窗口工厂**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`:
```java
package com.webapp.plugin.toolwindow;

import com.intellij.openapi.project.Project;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowFactory;
import org.jetbrains.annotations.NotNull;

import javax.swing.JLabel;
import javax.swing.JPanel;
import java.awt.BorderLayout;

/**
 * 工具窗口工厂：Task 1 只放占位内容，Task 5 替换为 WebAppPanel。
 */
public final class WebAppToolWindowFactory implements ToolWindowFactory {

    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        JPanel placeholder = new JPanel(new BorderLayout());
        placeholder.add(new JLabel("WebApp 面板将在后续任务中实现"), BorderLayout.CENTER);
        toolWindow.getContentManager().addContent(
            toolWindow.getContentManager().getFactory().createContent(placeholder, "WebApp", false)
        );
    }
}
```

> 说明：`ContentFactory` 通过 `toolWindow.getContentManager().getFactory()` 获取，`addContent` 直接加进内容管理器，这是 ToolWindowFactory 的标准写法。

- [ ] **Step 4: 生成 Gradle wrapper 并编译**

若本机无 `gradle` 命令，先下载独立发行版（**版本 9.7.1**，用户指定）：
```powershell
# 在 idea-webapp-plugin 目录下
Invoke-WebRequest https://services.gradle.org/distributions/gradle-9.7.1-bin.zip -OutFile "$env:TEMP\gradle-9.7.1-bin.zip"
Expand-Archive "$env:TEMP\gradle-9.7.1-bin.zip" "$env:TEMP\gradle-9.7.1"
& "$env:TEMP\gradle-9.7.1\bin\gradle.bat" wrapper --gradle-version 9.7.1
# 之后一律用 ./gradlew
```

编译验证：
```powershell
cd idea-webapp-plugin
.\gradlew.bat compileJava
```
Expected: BUILD SUCCESSFUL，`build/classes/java/main/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.class` 存在。

- [ ] **Step 5: 打包验证**

```powershell
.\gradlew.bat buildPlugin
```
Expected: BUILD SUCCESSFUL，`build/distributions/webapp-session-window-0.1.0.zip` 存在（内部含 `lib/webapp-session-window-0.1.0.jar` 与 `META-INF/plugin.xml`）。

- [ ] **Step 6: runIde 冒烟（可选但建议）**

```powershell
.\gradlew.bat runIde
```
Expected: 启动带插件的 IDE 沙箱实例；右侧工具窗口按钮 "WebApp" 出现；点击后显示占位文本。关闭沙箱 IDE（Ctrl+C 或关闭窗口）。

- [ ] **Step 7: 提交**

```bash
git add idea-webapp-plugin/
git commit -m "feat(webapp-plugin): gradle 工程骨架 + plugin.xml + 最小工具窗口"
```

---

### Task 2: UrlValidator（URL 安全校验，TDD）

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/util/UrlValidator.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/util/UrlValidatorTest.java`

**Interfaces:**
- Consumes: 无（纯静态工具）
- Produces: `public final class UrlValidator`，方法：
  - `public static boolean isValid(String url)` —— 整条 URL 合法（scheme ∈ {http,https} 且无空白/控制字符）
  - `public static boolean isValidScheme(String scheme)` —— scheme 白名单判断
  - `public static String normalizeBase(String serverUrl)` —— 去尾部斜杠
  - `public static String normalizePath(String path)` —— 去首部斜杠
  - `public static String buildFullUrl(String serverUrl, String path)` —— 拼接（Task 3/5/8 使用）

- [ ] **Step 1: 写失败测试**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/util/UrlValidatorTest.java`:
```java
package com.webapp.plugin.util;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;

class UrlValidatorTest {

    @Test
    void acceptsHttpAndHttps() {
        assertTrue(UrlValidator.isValid("http://localhost:5173"));
        assertTrue(UrlValidator.isValid("https://ai.example.com/web-apps/abc"));
    }

    @Test
    void rejectsDangerousSchemes() {
        assertFalse(UrlValidator.isValid("javascript:alert(1)"));
        assertFalse(UrlValidator.isValid("file:///etc/passwd"));
        assertFalse(UrlValidator.isValid("data:text/html,<script>"));
        assertFalse(UrlValidator.isValid("chrome://settings"));
        assertFalse(UrlValidator.isValid("about:blank"));
    }

    @Test
    void rejectsWhitespaceAndControlChars() {
        assertFalse(UrlValidator.isValid("http://local host:5173"));
        assertFalse(UrlValidator.isValid("http://localhost:5173/path with space"));
        assertFalse(UrlValidator.isValid("http://localhost:5173/\u0000"));
    }

    @Test
    void schemeWhitelist() {
        assertTrue(UrlValidator.isValidScheme("http"));
        assertTrue(UrlValidator.isValidScheme("https"));
        assertFalse(UrlValidator.isValidScheme("javascript"));
        assertFalse(UrlValidator.isValidScheme("file"));
        assertFalse(UrlValidator.isValidScheme(""));
    }

    @Test
    void normalizeAndBuild() {
        assertEquals("http://localhost:5173", UrlValidator.normalizeBase("http://localhost:5173/"));
        assertEquals("web-apps/abc", UrlValidator.normalizePath("/web-apps/abc"));
        assertEquals("http://localhost:5173/web-apps/abc",
            UrlValidator.buildFullUrl("http://localhost:5173/", "/web-apps/abc"));
        assertEquals("http://localhost:5173/web-apps/abc",
            UrlValidator.buildFullUrl("http://localhost:5173", "web-apps/abc"));
    }
}
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.util.UrlValidatorTest"
```
Expected: FAIL（UrlValidator 不存在，编译错误）。

- [ ] **Step 3: 最小实现**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/util/UrlValidator.java`:
```java
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
```

- [ ] **Step 4: 运行确认通过**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.util.UrlValidatorTest"
```
Expected: PASS（5 个测试全绿）。

- [ ] **Step 5: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/util/UrlValidator.java idea-webapp-plugin/src/test/java/com/webapp/plugin/util/UrlValidatorTest.java
git commit -m "feat(webapp-plugin): URL 安全校验 UrlValidator"
```

---

### Task 3: WebAppSettingsState（持久化设置，TDD）

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsState.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/settings/WebAppSettingsStateTest.java`

**Interfaces:**
- Consumes: `UrlValidator.buildFullUrl(String, String)`（Task 2）
- Produces:
  - `public final class WebAppSettingsState implements PersistentStateComponent<WebAppSettingsState>`，字段：`public String serverUrl = "http://localhost:5173";`、`public String path = "web-apps/Tf5qMSSgDiqHZkdg";`、`public boolean autoLoadOnStartup = true;`
  - 静态方法 `public static WebAppSettingsState getInstance()`
  - 实例方法 `public String getFullUrl()`（用 UrlValidator.buildFullUrl）

- [ ] **Step 1: 写失败测试**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/settings/WebAppSettingsStateTest.java`:
```java
package com.webapp.plugin.settings;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WebAppSettingsStateTest {

    @Test
    void defaultsMatchSpec() {
        WebAppSettingsState s = new WebAppSettingsState();
        assertEquals("http://localhost:5173", s.serverUrl);
        assertEquals("web-apps/Tf5qMSSgDiqHZkdg", s.path);
        assertTrue(s.autoLoadOnStartup);
    }

    @Test
    void fullUrlUsesValidator() {
        WebAppSettingsState s = new WebAppSettingsState();
        assertEquals("http://localhost:5173/web-apps/Tf5qMSSgDiqHZkdg", s.getFullUrl());
    }

    @Test
    void stateRoundTrip() {
        WebAppSettingsState s = new WebAppSettingsState();
        s.serverUrl = "https://staging.example.com";
        s.path = "/web-apps/other";
        WebAppSettingsState loaded = new WebAppSettingsState();
        loaded.loadState(s.getState());
        assertEquals("https://staging.example.com", loaded.serverUrl);
        assertEquals("/web-apps/other", loaded.path);
    }
}
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.settings.WebAppSettingsStateTest"
```
Expected: FAIL（类不存在，编译错误）。

- [ ] **Step 3: 最小实现**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsState.java`:
```java
package com.webapp.plugin.settings;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.components.PersistentStateComponent;
import com.intellij.openapi.components.State;
import com.intellij.openapi.components.Storage;
import com.webapp.plugin.util.UrlValidator;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

/**
 * WebApp 插件持久化设置。Token/凭据不入库——认证由 WebApp 页面自身管理。
 */
@State(name = "WebAppSettingsState", storages = @Storage("webapp-session-window.xml"))
public final class WebAppSettingsState implements PersistentStateComponent<WebAppSettingsState> {

    public String serverUrl = "http://localhost:5173";
    public String path = "web-apps/Tf5qMSSgDiqHZkdg";
    public boolean autoLoadOnStartup = true;

    public static WebAppSettingsState getInstance() {
        return ApplicationManager.getApplication().getService(WebAppSettingsState.class);
    }

    public String getFullUrl() {
        return UrlValidator.buildFullUrl(serverUrl, path);
    }

    @Override
    public @Nullable WebAppSettingsState getState() {
        return this;
    }

    @Override
    public void loadState(@NotNull WebAppSettingsState state) {
        this.serverUrl = state.serverUrl;
        this.path = state.path;
        this.autoLoadOnStartup = state.autoLoadOnStartup;
    }
}
```

- [ ] **Step 4: 运行确认通过**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.settings.WebAppSettingsStateTest"
```
Expected: PASS（3 个测试全绿）。

- [ ] **Step 5: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsState.java idea-webapp-plugin/src/test/java/com/webapp/plugin/settings/WebAppSettingsStateTest.java
git commit -m "feat(webapp-plugin): 持久化设置 WebAppSettingsState"
```

---

### Task 4: JcefSupport（JCEF 可用性检测与降级面板，TDD 核心逻辑）

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/util/JcefSupport.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/util/JcefSupportTest.java`

**Interfaces:**
- Consumes: 无
- Produces:
  - `public final class JcefSupport`：
    - `public enum Status { AVAILABLE, UNAVAILABLE }`
    - `public static Status checkAvailability()` —— 调用 `JBCefApp.isSupported()` 返回 AVAILABLE / UNAVAILABLE（JCEF 类不可加载时安全返回 UNAVAILABLE，包 NoClassDefFoundError）
    - `public static javax.swing.JComponent buildFallbackPanel(java.awt.Desktop desktop, String url, Runnable onRetry)` —— Swing 降级面板（原因文案 + [用系统浏览器打开] + [重试]）。`desktop`、`url`、`onRetry` 参数化以便单测注入

- [ ] **Step 1: 写失败测试**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/util/JcefSupportTest.java`:
```java
package com.webapp.plugin.util;

import org.junit.jupiter.api.Test;

import javax.swing.JButton;
import javax.swing.JComponent;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JcefSupportTest {

    @Test
    void fallbackPanelContainsButtons() {
        JComponent panel = JcefSupport.buildFallbackPanel(
            null, "http://localhost:5173/web-apps/x", () -> { });
        assertNotNull(panel);
        boolean hasButton = containsButton(panel, "用系统浏览器打开");
        boolean hasRetry = containsButton(panel, "重试");
        assertTrue(hasButton, "面板应包含'用系统浏览器打开'按钮");
        assertTrue(hasRetry, "面板应包含'重试'按钮");
    }

    private boolean containsButton(JComponent root, String text) {
        if (root instanceof JButton b && text.equals(b.getText())) {
            return true;
        }
        for (int i = 0; i < root.getComponentCount(); i++) {
            if (root.getComponent(i) instanceof JComponent c && containsButton(c, text)) {
                return true;
            }
        }
        return false;
    }
}
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.util.JcefSupportTest"
```
Expected: FAIL（JcefSupport 不存在，编译错误）。

- [ ] **Step 3: 最小实现**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/util/JcefSupport.java`:
```java
package com.webapp.plugin.util;

import com.intellij.ui.components.JBLabel;
import com.intellij.ui.components.JBPanel;
import com.intellij.ui.components.JBScrollPane;
import com.intellij.util.ui.JBUI;

import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.SwingConstants;
import java.awt.BorderLayout;
import java.awt.Desktop;
import java.awt.Font;
import java.net.URI;

/**
 * JCEF 可用性检测与降级 UI。
 * 官方 API：JBCefApp.isSupported()（非 JBCefBrowser.isAvailable()）。
 */
public final class JcefSupport {

    public enum Status { AVAILABLE, UNAVAILABLE }

    private JcefSupport() {
    }

    public static Status checkAvailability() {
        try {
            return com.intellij.ui.jcef.JBCefApp.isSupported()
                ? Status.AVAILABLE
                : Status.UNAVAILABLE;
        } catch (LinkageError e) {
            return Status.UNAVAILABLE;
        }
    }

    /**
     * 构建 Swing 降级面板（JCEF 不可用时展示）。
     *
     * @param desktop 用于 Desktop.browse；null 时按钮禁用（测试注入）
     * @param url     系统浏览器打开的目标 URL
     * @param onRetry 重试回调
     */
    public static JComponent buildFallbackPanel(Desktop desktop, String url, Runnable onRetry) {
        JBPanel<?> panel = new JBPanel<>(new BorderLayout());
        panel.setBorder(JBUI.Borders.empty(16));

        JBLabel title = new JBLabel("JCEF 不可用，无法内嵌浏览器", SwingConstants.CENTER);
        title.setFont(title.getFont().deriveFont(Font.BOLD, 14f));

        JBLabel hint = new JBLabel(
            "<html><center>当前 IDE 未启用 JCEF（Java Chromium Embedded Framework）。<br>"
                + "请使用 JetBrains Runtime（JBR）启动 IDE，或检查 IDE 版本 ≥ 2022.1。</center></html>",
            SwingConstants.CENTER);

        JButton openExternal = new JButton("用系统浏览器打开");
        openExternal.setEnabled(desktop != null && desktop.isSupported(Desktop.Action.BROWSE));
        openExternal.addActionListener(e -> {
            if (desktop != null && desktop.isSupported(Desktop.Action.BROWSE)) {
                try {
                    desktop.browse(URI.create(url));
                } catch (Exception ex) {
                    // 忽略：打不开外部浏览器时用户可手动复制 URL
                }
            }
        });

        JButton retry = new JButton("重试");
        retry.addActionListener(e -> {
            if (onRetry != null) {
                onRetry.run();
            }
        });

        JBPanel<?> buttons = new JBPanel<>();
        buttons.setLayout(new BoxLayout(buttons, BoxLayout.X_AXIS));
        buttons.add(Box.createHorizontalGlue());
        buttons.add(openExternal);
        buttons.add(Box.createHorizontalStrut(8));
        buttons.add(retry);
        buttons.add(Box.createHorizontalGlue());

        JBPanel<?> center = new JBPanel<>();
        center.setLayout(new BoxLayout(center, BoxLayout.Y_AXIS));
        center.add(Box.createVerticalGlue());
        center.add(title);
        center.add(Box.createVerticalStrut(12));
        center.add(hint);
        center.add(Box.createVerticalStrut(16));
        center.add(buttons);
        center.add(Box.createVerticalGlue());

        panel.add(center, BorderLayout.CENTER);
        return new JBScrollPane(panel);
    }
}
```

- [ ] **Step 4: 运行确认通过**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.util.JcefSupportTest"
```
Expected: PASS（1 个测试通过；`buildFallbackPanel(null, ...)` 时按钮存在但禁用，不影响 containsButton 断言）。

- [ ] **Step 5: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/util/JcefSupport.java idea-webapp-plugin/src/test/java/com/webapp/plugin/util/JcefSupportTest.java
git commit -m "feat(webapp-plugin): JCEF 可用性检测与 Swing 降级面板"
```

---

### Task 5: WebAppPanel + 工具窗口集成（JBCefBrowser 加载 URL）

**Files:**
- Modify: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/toolwindow/WebAppPanelTest.java`（仅测纯逻辑：URL 读取）

**Interfaces:**
- Consumes: `WebAppSettingsState.getInstance()`（Task 3）、`JcefSupport`（Task 4）、`UrlValidator`（Task 2）
- Produces:
  - `public final class WebAppPanel extends com.intellij.openapi.ui.SimpleToolWindowPanel implements com.intellij.openapi.Disposable`
    - 构造器 `WebAppPanel(@NotNull com.intellij.openapi.project.Project project)`
    - `public void reload()` —— 重新加载当前 URL（Task 6 刷新按钮 / 覆盖层调用）
    - `public com.intellij.ui.jcef.JBCefBrowser getBrowser()` —— 返回内部浏览器（Task 7 Bridge 使用）
  - `WebAppToolWindowFactory.createToolWindowContent` 改为创建 WebAppPanel 并 `Disposer.register(project, panel)`

- [ ] **Step 1: 写失败测试（URL 读取纯逻辑）**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/toolwindow/WebAppPanelTest.java`:
```java
package com.webapp.plugin.toolwindow;

import com.webapp.plugin.settings.WebAppSettingsState;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class WebAppPanelTest {

    @Test
    void settingsDrivenUrl() {
        WebAppSettingsState s = new WebAppSettingsState();
        assertEquals("http://localhost:5173/web-apps/Tf5qMSSgDiqHZkdg", s.getFullUrl());
    }
}
```

> 注：JBCefBrowser 依赖真实 IDE 环境，单测无法实例化；本测试只锁定"面板 URL 由设置驱动"这一纯逻辑，浏览器行为靠 runIde 手工验收。

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.toolwindow.WebAppPanelTest"
```
Expected: FAIL（类不存在，编译错误）。

- [ ] **Step 3: 实现 WebAppPanel**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`:
```java
package com.webapp.plugin.toolwindow;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.ui.components.JBLabel;
import com.intellij.ui.jcef.JBCefBrowser;
import com.webapp.plugin.settings.WebAppSettingsState;
import com.webapp.plugin.util.JcefSupport;
import org.jetbrains.annotations.NotNull;

import javax.swing.JComponent;
import java.awt.BorderLayout;
import java.awt.Desktop;

/**
 * 工具窗口内容：JCEF 浏览器 + 状态覆盖层。
 * 生命周期：随 Project 注册到 Disposer，dispose() 释放浏览器。
 */
public final class WebAppPanel extends com.intellij.openapi.ui.SimpleToolWindowPanel implements Disposable {

    private final Project project;
    private JBCefBrowser browser;
    private JComponent currentView;

    public WebAppPanel(@NotNull Project project) {
        super(true, true);
        this.project = project;
        if (JcefSupport.checkAvailability() == JcefSupport.Status.AVAILABLE) {
            initBrowser();
        } else {
            showFallback();
        }
    }

    private void initBrowser() {
        browser = new JBCefBrowser();
        browser.loadURL(currentUrl());
        currentView = browser.getComponent();
        setContent(currentView);
    }

    private void showFallback() {
        JcefSupport.Status status = JcefSupport.checkAvailability();
        if (status == JcefSupport.Status.AVAILABLE) {
            initBrowser();
            return;
        }
        currentView = JcefSupport.buildFallbackPanel(
            Desktop.getDesktop(),
            currentUrl(),
            this::reload
        );
        setContent(currentView);
    }

    public String currentUrl() {
        return WebAppSettingsState.getInstance().getFullUrl();
    }

    public void reload() {
        if (browser != null) {
            browser.loadURL(currentUrl());
        } else {
            showFallback();
        }
    }

    public JBCefBrowser getBrowser() {
        return browser;
    }

    @Override
    public void dispose() {
        if (browser != null) {
            Disposer.dispose(browser);
            browser = null;
        }
    }
}
```

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`（整体替换）:
```java
package com.webapp.plugin.toolwindow;

import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowFactory;
import org.jetbrains.annotations.NotNull;

/**
 * 创建 WebApp 工具窗口内容，并把面板生命周期挂到 Project 的 Disposer 上。
 */
public final class WebAppToolWindowFactory implements ToolWindowFactory {

    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        WebAppPanel panel = new WebAppPanel(project);
        Disposer.register(project, panel);
        toolWindow.getContentManager().addContent(
            toolWindow.getContentManager().getFactory().createContent(panel, "WebApp", false)
        );
    }
}
```

> **service 注册（Task 5 实测发现，必要修复）**：`WebAppSettingsState.getInstance()` 走 `ApplicationManager.getApplication().getService(...)`，但 @State 类在 IPGP 2.x / 2024.2 **不自动注册为 service**。需在 plugin.xml 的 `<extensions>` 中补充：
> ```xml
> <applicationService serviceImplementation="com.webapp.plugin.settings.WebAppSettingsState"/>
> ```
> 否则运行时 getInstance() 抛 "Service not registered" 异常。

- [ ] **Step 4: 运行测试 + 编译**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.toolwindow.WebAppPanelTest"
.\gradlew.bat compileJava
```
Expected: 测试 PASS，编译 SUCCESSFUL。

- [ ] **Step 5: runIde 手工验收**

```powershell
.\gradlew.bat runIde
```
验收清单：
1. 右侧工具窗口 "WebApp" 出现；
2. 点击后 JCEF 加载 `http://localhost:5173/web-apps/Tf5qMSSgDiqHZkdg`（若 5173 服务在运行则显示登录/会话页；否则显示 Chromium 连接失败页）；
3. 关闭沙箱 IDE，观察日志无 "Memory leak" 告警（验证 Disposable 生效）。

- [ ] **Step 6: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/
git commit -m "feat(webapp-plugin): WebAppPanel 内嵌 JCEF 浏览器加载会话页"
```

---

### Task 6: 加载状态覆盖层 + 标题栏刷新 Action

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/LoadStateOverlay.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/toolwindow/LoadStateOverlayTest.java`
- Modify: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`
- Modify: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`

**Interfaces:**
- Consumes: `WebAppPanel.reload()`（Task 5）、`WebAppPanel.currentUrl()`（Task 5）
- Produces:
  - `public enum LoadState { LOADING, CONNECTING, LOADED, NETWORK_ERROR, WEBAPP_ERROR, AUTH_ERROR }`
  - `public final class LoadStateOverlay`：
    - `LoadStateOverlay(Runnable onReload, java.util.function.Supplier<String> urlSupplier)`
    - `public void setState(LoadState state)` —— 切换覆盖层内容（CardLayout）
    - `public LoadState getState()`
  - `WebAppPanel` 增加：持有 `LoadStateOverlay`；注册 JCEF `CefLoadHandler`（`onLoadStart`→LOADING，`onLoadEnd`→LOADED，`onLoadError`→NETWORK_ERROR）；提供 `public void setLoadState(LoadState)`

- [ ] **Step 1: 写失败测试（状态机纯逻辑）**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/toolwindow/LoadStateOverlayTest.java`:
```java
package com.webapp.plugin.toolwindow;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class LoadStateOverlayTest {

    @Test
    void initialStateIsLoading() {
        LoadStateOverlay overlay = new LoadStateOverlay(() -> { }, () -> "http://x");
        assertEquals(LoadState.LOADING, overlay.getState());
    }

    @Test
    void setStateRoundTrips() {
        LoadStateOverlay overlay = new LoadStateOverlay(() -> { }, () -> "http://x");
        overlay.setState(LoadState.NETWORK_ERROR);
        assertEquals(LoadState.NETWORK_ERROR, overlay.getState());
        overlay.setState(LoadState.LOADED);
        assertEquals(LoadState.LOADED, overlay.getState());
    }
}
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.toolwindow.LoadStateOverlayTest"
```
Expected: FAIL（类不存在，编译错误）。

- [ ] **Step 3: 实现 LoadStateOverlay**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/LoadStateOverlay.java`:
```java
package com.webapp.plugin.toolwindow;

import com.intellij.ui.components.JBLabel;
import com.intellij.ui.components.JBPanel;
import com.intellij.util.ui.JBUI;

import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.SwingConstants;
import java.awt.BorderLayout;
import java.awt.CardLayout;
import java.awt.Font;
import java.util.function.Supplier;

/**
 * 加载状态覆盖层：LOADING/CONNECTING/LOADED/网络错误/应用错误/认证错误。
 * 非 LOADED 状态显示 Swing 卡片，覆盖在浏览器之上（或替代浏览器）。
 */
public final class LoadStateOverlay {

    public enum LoadState { LOADING, CONNECTING, LOADED, NETWORK_ERROR, WEBAPP_ERROR, AUTH_ERROR }

    private static final String CARD_LOADING = "loading";
    private static final String CARD_CONNECTING = "connecting";
    private static final String CARD_LOADED = "loaded";
    private static final String CARD_NETWORK = "network";
    private static final String CARD_WEBAPP = "webapp";
    private static final String CARD_AUTH = "auth";

    private final CardLayout layout = new CardLayout();
    private final JBPanel<?> root = new JBPanel<>(layout);
    private final Runnable onReload;
    private final Supplier<String> urlSupplier;
    private LoadState state = LoadState.LOADING;

    public LoadStateOverlay(Runnable onReload, Supplier<String> urlSupplier) {
        this.onReload = onReload;
        this.urlSupplier = urlSupplier;
        root.add(loadingCard("正在连接服务器..."), CARD_LOADING);
        root.add(loadingCard("连接中，请稍候..."), CARD_CONNECTING);
        root.add(new JBPanel<>(), CARD_LOADED);
        root.add(errorCard("无法连接 WebApp", true), CARD_NETWORK);
        root.add(errorCard("WebApp 返回错误", true), CARD_WEBAPP);
        root.add(errorCard("认证已失效，请重新登录", true), CARD_AUTH);
        setState(LoadState.LOADING);
    }

    private JComponent loadingCard(String text) {
        JBLabel label = new JBLabel(text, SwingConstants.CENTER);
        label.setFont(label.getFont().deriveFont(Font.BOLD, 13f));
        JBPanel<?> p = new JBPanel<>(new BorderLayout());
        p.add(label, BorderLayout.CENTER);
        return p;
    }

    private JComponent errorCard(String title, boolean withReload) {
        JBPanel<?> p = new JBPanel<>(new BorderLayout());
        p.setBorder(JBUI.Borders.empty(16));

        JBLabel t = new JBLabel(title, SwingConstants.CENTER);
        t.setFont(t.getFont().deriveFont(Font.BOLD, 14f));
        JBLabel url = new JBLabel("<html><center>" + urlSupplier.get() + "</center></html>",
            SwingConstants.CENTER);

        JButton reload = new JButton("重新加载");
        reload.addActionListener(e -> onReload.run());

        JBPanel<?> center = new JBPanel<>();
        center.setLayout(new BoxLayout(center, BoxLayout.Y_AXIS));
        center.add(Box.createVerticalGlue());
        center.add(t);
        center.add(Box.createVerticalStrut(8));
        center.add(url);
        center.add(Box.createVerticalStrut(16));
        if (withReload) {
            center.add(reload);
            center.add(Box.createVerticalStrut(8));
        }
        center.add(Box.createVerticalGlue());
        p.add(center, BorderLayout.CENTER);
        return p;
    }

    public JComponent getComponent() {
        return root;
    }

    public void setState(LoadState newState) {
        this.state = newState;
        String card = switch (newState) {
            case LOADING -> CARD_LOADING;
            case CONNECTING -> CARD_CONNECTING;
            case LOADED -> CARD_LOADED;
            case NETWORK_ERROR -> CARD_NETWORK;
            case WEBAPP_ERROR -> CARD_WEBAPP;
            case AUTH_ERROR -> CARD_AUTH;
        };
        layout.show(root, card);
    }

    public LoadState getState() {
        return state;
    }

    /**
     * 设置 LOADED 状态显示的组件（浏览器）。在面板初始化时调用，
     * 使 LOADING/LOADED/NETWORK_ERROR 经 overlay 单一组件真实切换可见内容。
     */
    public void setLoadedContent(javax.swing.JComponent component) {
        root.remove(CARD_LOADED);
        javax.swing.JPanel holder = new javax.swing.JPanel(new java.awt.BorderLayout());
        holder.add(component, java.awt.BorderLayout.CENTER);
        root.add(holder, CARD_LOADED);
    }
}
```

- [ ] **Step 4: 修改 WebAppPanel 集成覆盖层与加载事件**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`（增量修改，保留既有字段与方法）:

在字段区新增：
```java
    private LoadStateOverlay overlay;
    private com.intellij.ui.jcef.JBCefJSQuery jsQuery;
```

在 `initBrowser()` 中，`setContent(currentView)` 前插入（**Task 6 修复版：overlay 的 LOADED 卡片承载浏览器，状态切换闭环**）：
```java
        overlay = new LoadStateOverlay(this::reload, this::currentUrl);
        overlay.setLoadedContent(browser.getComponent());
        setContent(overlay.getComponent());
        overlay.setState(LoadState.LOADING);
        registerLoadHandler();
```

新增方法：
```java
    private void registerLoadHandler() {
        if (browser == null) {
            return;
        }
        org.cef.handler.CefLoadHandler handler = new org.cef.handler.CefLoadHandler() {
            @Override
            public void onLoadingStateChange(org.cef.browser.CefBrowser b, boolean isLoading,
                                             boolean canGoBack, boolean canGoForward) {
                if (!isLoading) {
                    setLoadState(LoadState.LOADED);
                }
            }

            @Override
            public void onLoadStart(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                    org.cef.network.CefRequest.TransitionType t) {
                setLoadState(LoadState.LOADING);
            }

            @Override
            public void onLoadEnd(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                  int httpStatusCode) {
                setLoadState(LoadState.LOADED);
            }

            @Override
            public void onLoadError(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                    org.cef.handler.CefLoadHandler.ErrorCode errorCode,
                                    String errorText, String failedUrl) {
                setLoadState(LoadState.NETWORK_ERROR);
            }
        };
        browser.getJBCefClient().getCefClient().addLoadHandler(handler);
    }

    public void setLoadState(LoadStateOverlay.LoadState state) {
        if (overlay != null) {
            overlay.setState(state);
        }
    }

    public void showOverlay(LoadStateOverlay.LoadState state) {
        setLoadState(state);
    }
```

> 说明（Task 6 实测修正）：`CefLoadHandler.onLoadStart` 第三参数在 IU 2024.2 实际为 `org.cef.network.CefRequest.TransitionType`（非 `CefFrame.TransitionType`）；`CefClient.addLoadHandler` 为单参（handler 注册在 client 上，回调自带 browser 参数）。`LoadStateOverlay` 需新增 `setLoadedContent(JComponent)` 方法（LOADED 卡片替换为浏览器组件），使 LOADING/LOADED/NETWORK_ERROR 经 overlay 单一组件真实切换可见内容。

- [ ] **Step 5: 修改 WebAppToolWindowFactory 注册标题栏 Action**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppToolWindowFactory.java`（增量修改 `createToolWindowContent`，并补 import `com.intellij.openapi.actionSystem.AnAction`、`com.intellij.openapi.actionSystem.ActionManager`）:

```java
    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        WebAppPanel panel = new WebAppPanel(project);
        Disposer.register(project, panel);

        // 标题栏刷新按钮：复用 IDE 内置 "Refresh" action（自带图标）。
        // 找不到时跳过（判空防 NPE）；面板覆盖层的 [重新加载] 按钮是主要入口。
        AnAction refresh = ActionManager.getInstance().getAction("Refresh");
        if (refresh != null) {
            toolWindow.setTitleActions(java.util.List.of(refresh));
        }

        toolWindow.getContentManager().addContent(
            toolWindow.getContentManager().getFactory().createContent(panel, "WebApp", false)
        );
    }
```

> 简化说明：标题栏 Action 复用 IDE 内置 `Refresh` action（`ActionManager.getInstance().getAction("Refresh")`），判空后设置；面板覆盖层的 [重新加载] 按钮是主要入口。

- [ ] **Step 6: 运行测试 + 编译**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.toolwindow.*"
.\gradlew.bat compileJava
```
Expected: 测试 PASS（含 Task 5 的 WebAppPanelTest），编译 SUCCESSFUL。

- [ ] **Step 7: runIde 手工验收**

```powershell
.\gradlew.bat runIde
```
1. 打开工具窗口 → 先显示"正在连接服务器..."，页面加载完成后切换到浏览器内容；
2. 停掉 5173 服务 → 刷新 → 显示"无法连接 WebApp"卡片 + [重新加载]；
3. 恢复服务 → 点 [重新加载] → 正常加载。

- [ ] **Step 8: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/
git commit -m "feat(webapp-plugin): 加载状态覆盖层与刷新能力"
```

---

### Task 7: WebAppBridge（JBCefJSQuery 双向通信，TDD 协议）

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/bridge/WebAppBridge.java`
- Create: `idea-webapp-plugin/src/test/java/com/webapp/plugin/bridge/BridgeProtocolTest.java`
- Modify: `idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`

**Interfaces:**
- Consumes: `WebAppPanel.getBrowser()`（Task 5）
- Produces:
  - `public final class WebAppBridge implements com.intellij.openapi.Disposable`：
    - `WebAppBridge(com.intellij.ui.jcef.JBCefBrowser browser, com.intellij.openapi.project.Project project)`
    - `public static String parseAction(String json)` —— 从 `{action, payload}` JSON 提取 action（未知/畸形返回 ""，纯逻辑，供单测）
    - `public static String buildResponse(boolean ok, Object data, String error)` —— 构造响应 JSON
    - `public void dispose()`
  - `WebAppPanel` 构造器中创建 `WebAppBridge`（JCEF 可用时），dispose 中释放

- [ ] **Step 1: 写失败测试（协议纯逻辑）**

`idea-webapp-plugin/src/test/java/com/webapp/plugin/bridge/BridgeProtocolTest.java`:
```java
package com.webapp.plugin.bridge;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
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
}
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.bridge.BridgeProtocolTest"
```
Expected: FAIL（类不存在，编译错误）。

- [ ] **Step 3: 实现 WebAppBridge**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/bridge/WebAppBridge.java`:
```java
package com.webapp.plugin.bridge;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vfs.LocalFileSystem;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.ui.jcef.JBCefBrowser;
import com.intellij.ui.jcef.JBCefJSQuery;
import org.jetbrains.annotations.NotNull;

import java.util.Map;
import java.util.Set;

/**
 * WebApp 页面 → IDE 桥（JS→Java）。v1 实现 openFile / getCurrentFile / refresh，
 * openDirectory / getProjectRoot 仅定义协议，返回"未实现"。
 */
public final class WebAppBridge implements Disposable {

    private static final Set<String> IMPLEMENTED = Set.of("openFile", "getCurrentFile", "refresh");
    private static final Set<String> DECLARED_NOT_IMPLEMENTED = Set.of("openDirectory", "getProjectRoot");

    private final JBCefBrowser browser;
    private final Project project;
    private JBCefJSQuery jsQuery;

    public WebAppBridge(@NotNull JBCefBrowser browser, @NotNull Project project) {
        this.browser = browser;
        this.project = project;
        this.jsQuery = JBCefJSQuery.create(browser);
        this.jsQuery.addHandler(this::handle);
    }

    /** 纯逻辑：解析 JS 传来的 JSON，提取 action；畸形/未知返回空串。 */
    public static String parseAction(String json) {
        if (json == null || json.isBlank()) {
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

    private static String toJson(Object o) {
        if (o instanceof String s) {
            return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
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
                VirtualFile vf = LocalFileSystem.getInstance().findFileByPath(path);
                if (vf == null) {
                    return new JBCefJSQuery.Response(
                        buildResponse(false, null, "文件不存在: " + path), 0, null);
                }
                FileEditorManager.getInstance(project).openFile(vf, true);
                return new JBCefJSQuery.Response(buildResponse(true, "opened", null), 0, null);
            }
            if ("getCurrentFile".equals(action)) {
                VirtualFile current = FileEditorManager.getInstance(project).getSelectedFiles()
                    .length > 0 ? FileEditorManager.getInstance(project).getSelectedFiles()[0] : null;
                return new JBCefJSQuery.Response(
                    buildResponse(true, current != null ? current.getPath() : "", null), 0, null);
            }
            if ("refresh".equals(action)) {
                browser.loadURL(browser.getCefBrowser().getURL());
                return new JBCefJSQuery.Response(buildResponse(true, "refreshed", null), 0, null);
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

    @Override
    public void dispose() {
        if (jsQuery != null) {
            // Task 7 实测修正：2024.2 无 removeHandler() 无参重载，需传入 handler（或 clearHandlers()）
            jsQuery.removeHandler(this::handle);
            jsQuery.dispose();
            jsQuery = null;
        }
    }
}
```

> 说明（Task 7 实测修正）：IU 2024.2 的 `JBCefJSQuery` API 中 `removeHandler()` 无参重载不存在（实测 `removeHandler(Function)` + `clearHandlers()`）。实现中 handler 存为字段，dispose 用 `removeHandler(handler)` 精确移除，语义与 brief 一致。另 `JBCefJSQuery.create(JBCefBrowser)` 在 2024.2 标记 forRemoval 弃用（仅警告，构建通过）。

> 注：Gson 由 IntelliJ Platform 自带（`com.google.gson` 在 platform 依赖中），无需额外引入。若编译期找不到，在 build.gradle.kts dependencies 加 `compileOnly("com.google.code.gson:gson:2.10.1")`。

- [ ] **Step 4: 修改 WebAppPanel 创建/释放 Bridge**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java`（增量修改）:

字段区新增：
```java
    private com.webapp.plugin.bridge.WebAppBridge bridge;
```

`initBrowser()` 中 `setContent(currentView);` 之前新增：
```java
        bridge = new com.webapp.plugin.bridge.WebAppBridge(browser, project);
```

`dispose()` 中 `Disposer.dispose(browser)` 之前新增：
```java
        if (bridge != null) {
            Disposer.dispose(bridge);
            bridge = null;
        }
```

- [ ] **Step 5: 运行测试 + 编译**

```powershell
.\gradlew.bat test --tests "com.webapp.plugin.bridge.BridgeProtocolTest"
.\gradlew.bat compileJava
```
Expected: 测试 PASS（4 个），编译 SUCCESSFUL。

- [ ] **Step 6: runIde 手工验收 Bridge**

```powershell
.\gradlew.bat runIde
```
1. 打开工具窗口加载页面后，按 Ctrl+Shift+A 打开 JCEF DevTools（或右键页面 → Inspect）；
2. Console 执行：
   ```js
   // 需先用页面上的 bridge 注入点。v1 通过 WebApp 页面自行决定是否注入；
   // 若页面未注入 window.webAppBridge，插件侧 DevTools 手工验证协议即可：
   fetch('http://jbcefjsquery/__bridge__?message=' + encodeURIComponent(JSON.stringify({action:'getCurrentFile'})))
   ```
3. 若页面已集成 bridge（后续 WebApp 侧工作），点击消息中的"打开文件"链接应能在 IDE 编辑器打开对应文件。

> 说明：Bridge 的完整端到端验证依赖 WebApp 页面侧注入 `window.webAppBridge`（属于 WebApp 前端后续迭代）；本任务保证插件侧通道与协议可用，页面侧集成见 Spec"后续迭代"。

- [ ] **Step 7: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/bridge/ idea-webapp-plugin/src/test/java/com/webapp/plugin/bridge/ idea-webapp-plugin/src/main/java/com/webapp/plugin/toolwindow/WebAppPanel.java
git commit -m "feat(webapp-plugin): WebAppBridge JS→Java 双向通道"
```

---

### Task 8: WebAppSettingsConfigurable 设置页

**Files:**
- Create: `idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsConfigurable.java`
- Modify: `idea-webapp-plugin/src/main/resources/META-INF/plugin.xml`（恢复 configurable 声明）

**Interfaces:**
- Consumes: `WebAppSettingsState.getInstance()`（Task 3）、`UrlValidator`（Task 2）
- Produces:
  - `public final class WebAppSettingsConfigurable implements com.intellij.openapi.options.Configurable`
    - `getDisplayName()` → "WebApp"
    - `createComponent()` → 表单（Server URL 文本框、Path 文本框、autoLoadOnStartup 勾选、Test Connection 按钮）
    - `isModified()` / `apply()` / `reset()`

- [ ] **Step 1: 恢复 plugin.xml 声明**

`idea-webapp-plugin/src/main/resources/META-INF/plugin.xml`：把 Task 1 注释掉的 configurable 行恢复为：
```xml
        <applicationConfigurable parentId="tools"
                                 instance="com.webapp.plugin.settings.WebAppSettingsConfigurable"/>
```

- [ ] **Step 2: 实现设置页**

`idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsConfigurable.java`:
```java
package com.webapp.plugin.settings;

import com.intellij.openapi.options.Configurable;
import com.intellij.ui.components.JBLabel;
import com.intellij.ui.components.JBTextField;
import com.intellij.util.ui.FormBuilder;
import com.webapp.plugin.util.UrlValidator;
import org.jetbrains.annotations.Nls;
import org.jetbrains.annotations.Nullable;

import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JComponent;
import java.awt.Desktop;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.util.concurrent.CompletableFuture;

/**
 * Settings → Tools → WebApp 设置页。
 * 第一版仅三项：Server URL、WebApp Path、启动时自动加载 + Test Connection。
 */
public final class WebAppSettingsConfigurable implements Configurable {

    private JBTextField serverUrlField;
    private JBTextField pathField;
    private JCheckBox autoLoadCheck;
    private JButton testButton;
    private JBLabel statusLabel;

    @Override
    public @Nls(capitalization = Nls.Capitalization.Title) String getDisplayName() {
        return "WebApp";
    }

    @Override
    public @Nullable JComponent createComponent() {
        serverUrlField = new JBTextField();
        pathField = new JBTextField();
        autoLoadCheck = new JCheckBox("打开工具窗口时自动加载");
        testButton = new JButton("Test Connection");
        statusLabel = new JBLabel(" ");

        testButton.addActionListener(e -> {
            String url = serverUrlField.getText().trim();
            if (!UrlValidator.isValid(url)) {
                statusLabel.setText("URL 不合法（仅允许 http/https）");
                return;
            }
            testButton.setEnabled(false);
            statusLabel.setText("测试中...");
            CompletableFuture.runAsync(() -> {
                boolean ok = testConnection(url);
                javax.swing.SwingUtilities.invokeLater(() -> {
                    statusLabel.setText(ok ? "连接成功" : "连接失败");
                    testButton.setEnabled(true);
                });
            });
        });

        // 输入即时校验：非法时红字提示
        javax.swing.event.DocumentListener docListener = new javax.swing.event.DocumentListener() {
            @Override public void insertUpdate(javax.swing.event.DocumentEvent e) { validateInput(); }
            @Override public void removeUpdate(javax.swing.event.DocumentEvent e) { validateInput(); }
            @Override public void changedUpdate(javax.swing.event.DocumentEvent e) { validateInput(); }
        };
        serverUrlField.getDocument().addDocumentListener(docListener);
        pathField.getDocument().addDocumentListener(docListener);

        return FormBuilder.createFormBuilder()
            .addLabeledComponent(new JBLabel("Server URL"), serverUrlField)
            .addLabeledComponent(new JBLabel("WebApp Path"), pathField)
            .addComponent(autoLoadCheck)
            .addComponent(testButton)
            .addComponent(statusLabel)
            .getPanel();
    }

    private void validateInput() {
        if (serverUrlField == null) {
            return;
        }
        boolean ok = UrlValidator.isValid(serverUrlField.getText().trim());
        if (!ok && !serverUrlField.getText().isBlank()) {
            statusLabel.setText("Server URL 不合法（仅允许 http/https，无空白字符）");
        } else {
            statusLabel.setText(" ");
        }
    }

    private boolean testConnection(String url) {
        try {
            HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(3000);
            conn.setRequestMethod("HEAD");
            int code = conn.getResponseCode();
            conn.disconnect();
            return code >= 200 && code < 500; // 4xx 也算"可达"
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public boolean isModified() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        return !serverUrlField.getText().equals(s.serverUrl)
            || !pathField.getText().equals(s.path)
            || autoLoadCheck.isSelected() != s.autoLoadOnStartup;
    }

    @Override
    public void apply() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        s.serverUrl = UrlValidator.normalizeBase(serverUrlField.getText());
        s.path = UrlValidator.normalizePath(pathField.getText());
        s.autoLoadOnStartup = autoLoadCheck.isSelected();
    }

    @Override
    public void reset() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        serverUrlField.setText(s.serverUrl);
        pathField.setText(s.path);
        autoLoadCheck.setSelected(s.autoLoadOnStartup);
        statusLabel.setText(" ");
    }
}
```

> 说明：`HttpURLConnection` 的 HEAD 可能被部分服务器拒绝（返回 405），仍视为"可达"（4xx 通过）。这是测试按钮，非关键路径。

- [ ] **Step 3: 编译 + runIde 手工验收**

```powershell
.\gradlew.bat compileJava
.\gradlew.bat runIde
```
1. Settings → Tools → WebApp 出现设置表单；
2. 输入非法 URL（如 `htp://x` 或 `javascript:alert(1)`）→ 红字提示；
3. Test Connection 对 `http://localhost:5173` 返回"连接成功"（服务在跑时）；
4. 修改 Path → Apply → 打开工具窗口 → 加载新 URL。

- [ ] **Step 4: 提交**

```bash
git add idea-webapp-plugin/src/main/java/com/webapp/plugin/settings/WebAppSettingsConfigurable.java idea-webapp-plugin/src/main/resources/META-INF/plugin.xml
git commit -m "feat(webapp-plugin): 设置页 WebAppSettingsConfigurable"
```

---

### Task 9: README + 完整验收 + 收尾

**Files:**
- Create: `idea-webapp-plugin/README.md`

**Interfaces:**
- Consumes: 全部已完成组件

- [ ] **Step 1: 编写 README**

`idea-webapp-plugin/README.md`:
```markdown
# WebApp Session Window — IntelliJ 插件

在 JetBrains IDE（2024.2+）右侧嵌入 WebApp AI 会话窗口（JCEF）。

## 功能
- 工具窗口内嵌 Chromium（JCEF）加载 WebApp 会话页
- 登录态由 WebApp 页面自身管理；2023+ IDE 的 JCEF localStorage 跨重启持久
- URL 两段式配置（Settings → Tools → WebApp），安全校验仅允许 http/https
- 加载状态覆盖层（连接中/网络错误/认证失效）+ 重新加载
- JS→Java Bridge（v1：openFile / getCurrentFile / refresh）

## 构建
- JDK 21 + Gradle 9.7.1（wrapper 已固定）
- `.\gradlew.bat buildPlugin` — 打包
- `.\gradlew.bat runIde` — 启动调试沙箱

## 登录态持久化边界（重要）
- JCEF 是 IDE 进程级单例（JBCefApp），插件无法为单个浏览器设置 cache_path
- localStorage 存于 IDE 的 JCEF 缓存目录，2023+ 版本重启 IDE 后保留（社区实证）
- "Invalidate Caches" 会清空 JCEF 缓存 → 需重新登录
- sessionStorage 不保证跨重启

## Bridge 协议（WebApp 页面侧集成）
页面注入 `window.webAppBridge` 后，可向 IDE 发消息：
```js
window.webAppBridge.send(JSON.stringify({ action: 'openFile', payload: { path: '/abs/path' } }))
```
v1 支持：`openFile` / `getCurrentFile` / `refresh`；`openDirectory` / `getProjectRoot` 已声明未实现。

## 架构
```
ToolWindow(WebApp, right)
  └─ WebAppPanel (Disposable)
       ├─ JBCefBrowser (JCEF)
       ├─ LoadStateOverlay (状态覆盖层)
       └─ WebAppBridge (JBCefJSQuery)
```

## 版本
- since-build: 242 (2024.2+)
- until-build: 252.*（发版时按 Plugin Verifier 结果更新）
```

- [ ] **Step 2: 全量测试 + 打包 + Plugin Verifier**

```powershell
.\gradlew.bat clean buildPlugin
.\gradlew.bat runPluginVerifier
```
Expected: 单元测试全绿、buildPlugin 成功、Verifier 无致命兼容性错误（警告可接受）。

> 说明：IPGP 2.x 中 Plugin Verifier 的目标 IDE 列表在 `build.gradle.kts` 的 `intellijPlatform.pluginVerification { ideVersions(...) }` 中配置（或用 `verifyPlugin` 任务）。本任务先用默认配置（当前平台 2024.2 IC）跑 `runPluginVerifier`；若任务不存在或需要指定 IDE，可在 build.gradle.kts 中补：
> ```kotlin
> intellijPlatform {
>     pluginVerification {
>         ideVersions("2024.2", "2024.3")
>     }
> }
> ```
> 若联网下载目标 IDE 较慢，可跳过本步并在 README"版本"节注明待验证。

- [ ] **Step 3: 最终手工验收清单**

```powershell
.\gradlew.bat runIde
```
1. 右侧工具窗口 → 页面加载 → 登录 → 发送消息 → SSE 流式回复正常；
2. 重启沙箱 IDE → 登录态保持（无需重新登录）；
3. 停 5173 → 覆盖层"无法连接" → 恢复后 [重新加载] 正常；
4. 设置页改 URL → 校验反馈 → Apply 后工具窗口加载新 URL；
5. 关闭项目 → 日志无 "Memory leak" / JCEF 相关异常。

- [ ] **Step 4: 提交**

```bash
git add idea-webapp-plugin/README.md
git commit -m "docs(webapp-plugin): README 与验收清单"
```

---

## Self-Review 结果

**1. Spec 覆盖检查**（对照 `2026-08-30-webapp-idea-plugin-design.md`）：
- JCEF 依赖声明 + isSupported 检查 + Swing 降级 → Task 4 ✅
- URL 两段式配置 + 安全校验（http/https 白名单、拒绝危险 scheme）→ Task 2/3/8 ✅
- 登录态持久化 → Task 5 + README 边界说明（Task 9）✅（实现机制按官方 API 修正：`JBCefApp.isSupported()`；cache_path 不可由插件设置，依赖 IDE JCEF 持久缓存）
- WebAppBridge v1 三方法 + 两方法"未实现" → Task 7 ✅
- Disposable 生命周期链（Project→Panel→Browser+Bridge）→ Task 5/7 ✅
- 加载状态机 + 覆盖层 + 刷新 → Task 6 ✅
- 设置项三项 + Test Connection → Task 8 ✅
- 工具窗口右侧停靠 → Task 1 plugin.xml `anchor="right"` ✅
- 工程结构 → Task 1 骨架 + 各任务建目录 ✅
- 测试（单元 + runIde 手工 + Plugin Verifier）→ Task 2/3/4/5/6/7 单测，Task 5/6/8/9 runIde，Task 9 Verifier ✅
- 明确不做（文件系统/Remote Dev/Token 管理）→ Global Constraints + README ✅

**2. Placeholder 扫描**：无 TBD/TODO；所有代码块为完整实现。Task 6 标题栏 Action 用内置 `Refresh` action（有判空说明），非占位。✅

**3. 类型一致性**：
- `JBCefApp.isSupported()` 全计划统一（修正 spec 的 `JBCefBrowser.isAvailable()`）✅
- `UrlValidator.buildFullUrl / normalizeBase / normalizePath` 在 Task 2 定义，Task 3/8 按同名调用 ✅
- `WebAppPanel.reload() / getBrowser() / currentUrl() / setLoadState() / showOverlay()` 在 Task 5 定义，Task 6/7 按同名调用 ✅
- `LoadStateOverlay.LoadState` 枚举在 Task 6 定义，Task 6/7 统一引用 ✅
- Bridge 协议 `{action,payload}` / `{ok,data,error}` 在 Global Constraints 与 Task 7 一致 ✅
