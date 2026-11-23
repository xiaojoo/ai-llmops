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
    // IntelliJ platform 测试框架的 JUnit5TestSessionListener 依赖 junit.framework.TestCase（JUnit4），
    // 缺失会导致 Gradle Test Executor 无法启动（NoClassDefFoundError），仅测试作用域。
    testImplementation("junit:junit:4.13.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")

    intellijPlatform {
        // 沙箱 IDE 版本：2025.3 Ultimate（本地已有完整发行版缓存，无需重新下载）。
        // 2025.3 的 Gradle 插件已修复 Java 25 兼容性数据解析问题，不再刷
        // GradleJvmSupportMatrix IllegalArgumentException: 25 的 SEVERE/WARN 噪音。
        intellijIdeaUltimate("2025.3")
        testFramework(org.jetbrains.intellij.platform.gradle.TestFrameworkType.Platform)
    }
}

intellijPlatform {
    // 沙箱环境无法启动 headless IDE（DirectoryLock 绑定 Unix domain socket 被拒，
    // 与 runIde 同源限制）；内部插件设置搜索框索引非必需，禁用消除构建环境依赖。
    buildSearchableOptions = false
    pluginConfiguration {
        ideaVersion {
            sinceBuild = "253"
            // 覆盖到 2026.1（用户日常 IDE 为 IU-261.x）；未来升级 IDE 需同步上调
            untilBuild = "261.*"
        }
    }
}

tasks {
    test {
        useJUnitPlatform()
    }
    // runIde 控制台只显示 error+：2024.2 的 Gradle 插件拉取兼容性数据会刷 WARN 噪音，
    // 2025.3 已修复；保留 error 级别让控制台保持干净（完整日志仍在沙箱 idea.log）。
    named<org.gradle.api.tasks.JavaExec>("runIde") {
        systemProperty("intellij.console.log.level", "error")
    }
}

// ===== Web UI 打包产物同步 =====
// 从 ai-llmops-web 的 vite 构建产物（dist/agent-chat-embed/）复制到插件资源目录，
// 使 JCEF 能加载本地打包的聊天界面。
// 前置：在 ai-llmops-web 下执行 `npx vite build --config vite.agent-chat.config.ts`
// 产物路径（vite 保留相对项目根的输入路径，输入 agent-chat-embed/index.html + outDir=dist）：
//   dist/agent-chat-embed/index.html                       （当前扁平单文件产物）
val webDistDir = rootProject.file("../ai-llmops-web/dist")
val webUiFlatIndex = webDistDir.resolve("agent-chat-embed/index.html")
val webUiTarget = layout.projectDirectory.dir("src/main/resources/web-ui")

val syncWebUi by tasks.registering(Sync::class) {
    // 仅接受当前 vite 配置的规范产物（dist/agent-chat-embed/index.html 单文件）。
    // 旧嵌套/多文件产物已废弃：file:// 下外部 module 脚本被 Chromium 拦截，加载必然失败。
    onlyIf { webUiFlatIndex.exists() }

    from(webUiFlatIndex)
    into(webUiTarget)
    include("**/*")

    // 注意：产物保持 vite 原样，不要改写 <script type="module">。
    // module 脚本是延迟执行的（DOM 解析完成后才跑），此时 #app 已存在，mount 才能成功；
    // 若剥掉 type="module" 变成普通脚本，会在 <head> 解析时立即执行，此时 #app 尚不存在，
    // mount("#app") 静默失败 → 整页空白。file:// 下内联 module 脚本可正常执行
    // （vite-plugin-singlefile 内联所有资源正是为 file:// 场景设计）。
}

tasks.named("processResources") {
    dependsOn(syncWebUi)
}
