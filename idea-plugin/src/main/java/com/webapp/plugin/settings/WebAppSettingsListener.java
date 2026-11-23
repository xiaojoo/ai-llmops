package com.webapp.plugin.settings;

/**
 * WebApp 设置变更监听器。
 * 由 {@link WebAppSettingsConfigurable#apply()} 通过
 * {@link WebAppSettingsState#SETTINGS_CHANGED} 发布，WebAppPanel 订阅后 reload()，
 * 使新设置立即生效。
 */
public interface WebAppSettingsListener {

    void settingsChanged();
}
