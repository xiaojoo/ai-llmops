package com.webapp.plugin.settings;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.components.PersistentStateComponent;
import com.intellij.openapi.components.State;
import com.intellij.openapi.components.Storage;
import com.intellij.util.messages.Topic;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

/**
 * WebApp 插件持久化设置。
 * 新架构：插件直连后端 API（自建聊天 UI），不再加载前端页面。
 * 存后端地址、WebApp token、登录 token（authToken 由登录动作写入，持久化以跨重启保持登录）。
 */
@State(name = "WebAppSettingsState", storages = @Storage("webapp-session-window.xml"))
public final class WebAppSettingsState implements PersistentStateComponent<WebAppSettingsState> {

    /** 设置变更事件：WebAppSettingsConfigurable.apply() 发布，面板订阅后刷新。 */
    public static final Topic<WebAppSettingsListener> SETTINGS_CHANGED =
        Topic.create("webapp.settings.changed", WebAppSettingsListener.class);

    /** 后端 API 基地址（FastAPI，含端口）。 */
    public String backendUrl = "http://localhost:5000";

    /** WebApp 标识 token（路径中的那个）。 */
    public String webAppToken = "M0GEcQmJvGMCN5ou";

    /** 登录 access_token（持久化以跨重启保持登录）。 */
    public String authToken = "";

    /** 最近登录账号（设置页回显用）。 */
    public String email = "";

    /** 最近一次会话 id（聊天过程中回写，插件重新打开时恢复上次会话）。 */
    public String lastConversationId = "";

    /** 兼容旧字段（JCEF 容器时代），loadState 容错保留。 */
    public String serverUrl = "http://localhost:5173";
    public String path = "web-apps/M0GEcQmJvGMCN5ou";
    public boolean autoLoadOnStartup = true;

    public static WebAppSettingsState getInstance() {
        return ApplicationManager.getApplication().getService(WebAppSettingsState.class);
    }

    public boolean isLoggedIn() {
        return authToken != null && !authToken.isBlank();
    }

    public void clearAuth() {
        authToken = "";
    }

    @Override
    public @Nullable WebAppSettingsState getState() {
        return this;
    }

    @Override
    public void loadState(@NotNull WebAppSettingsState state) {
        // 新字段
        this.backendUrl = state.backendUrl != null ? state.backendUrl : "http://localhost:5000";
        this.webAppToken = state.webAppToken != null ? state.webAppToken : "M0GEcQmJvGMCN5ou";
        this.authToken = state.authToken != null ? state.authToken : "";
        this.email = state.email != null ? state.email : "";
        this.lastConversationId = state.lastConversationId != null ? state.lastConversationId : "";
        // 旧字段（容错）
        this.serverUrl = state.serverUrl != null ? state.serverUrl : "http://localhost:5173";
        this.path = state.path != null ? state.path : "web-apps/M0GEcQmJvGMCN5ou";
        this.autoLoadOnStartup = state.autoLoadOnStartup;
    }
}
