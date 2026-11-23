package com.webapp.plugin.settings;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.options.Configurable;
import com.intellij.ui.components.JBLabel;
import com.intellij.ui.components.JBTextField;
import com.intellij.util.ui.FormBuilder;
import com.webapp.plugin.util.UrlValidator;
import org.jetbrains.annotations.Nls;
import org.jetbrains.annotations.Nullable;

import javax.swing.JButton;
import javax.swing.JComponent;
import java.net.HttpURLConnection;
import java.net.URI;
import java.util.concurrent.CompletableFuture;

/**
 * Settings → Tools → WebApp 设置页（新架构：插件直连后端 API）。
 * 字段：后端地址（backendUrl）、WebApp token、已登录账号展示 + 退出登录。
 */
public final class WebAppSettingsConfigurable implements Configurable {

    private JBTextField backendUrlField;
    private JBTextField webAppTokenField;
    private JBLabel accountLabel;
    private JButton logoutButton;
    private JButton testButton;
    private JBLabel statusLabel;

    @Override
    public @Nls(capitalization = Nls.Capitalization.Title) String getDisplayName() {
        return "WebApp";
    }

    @Override
    public @Nullable JComponent createComponent() {
        backendUrlField = new JBTextField();
        webAppTokenField = new JBTextField();
        accountLabel = new JBLabel(" ");
        logoutButton = new JButton("退出登录");
        testButton = new JButton("Test Connection");
        statusLabel = new JBLabel(" ");

        // Test Connection：探测后端地址可达性
        testButton.addActionListener(e -> {
            String url = backendUrlField.getText().trim();
            if (!UrlValidator.isValid(url)) {
                statusLabel.setText("地址不合法（仅允许 http/https）");
                statusLabel.setForeground(java.awt.Color.RED);
                return;
            }
            testButton.setEnabled(false);
            statusLabel.setText("测试中...");
            statusLabel.setForeground(null);
            CompletableFuture.runAsync(() -> {
                boolean ok = testConnection(url);
                javax.swing.SwingUtilities.invokeLater(() -> {
                    if (ok) {
                        statusLabel.setText("连接成功");
                        statusLabel.setForeground(new java.awt.Color(0, 128, 0));
                    } else {
                        statusLabel.setText("连接失败");
                        statusLabel.setForeground(java.awt.Color.RED);
                    }
                    testButton.setEnabled(true);
                });
            });
        });

        // 退出登录：清 token
        logoutButton.addActionListener(e -> {
            WebAppSettingsState.getInstance().clearAuth();
            refreshAccount();
            statusLabel.setText("已退出登录");
            statusLabel.setForeground(null);
        });

        return FormBuilder.createFormBuilder()
            .addLabeledComponent(new JBLabel("后端地址 (FastAPI)"), backendUrlField)
            .addLabeledComponent(new JBLabel("WebApp Token"), webAppTokenField)
            .addLabeledComponent(new JBLabel("登录账号"), accountLabel)
            .addComponent(logoutButton)
            .addComponent(testButton)
            .addComponent(statusLabel)
            .getPanel();
    }

    private void refreshAccount() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        if (s.isLoggedIn()) {
            accountLabel.setText(s.email.isBlank() ? "已登录" : s.email);
            logoutButton.setEnabled(true);
        } else {
            accountLabel.setText("未登录");
            logoutButton.setEnabled(false);
        }
    }

    private boolean testConnection(String url) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) URI.create(url).toURL().openConnection();
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(3000);
            conn.setRequestMethod("HEAD");
            int code = conn.getResponseCode();
            return code >= 200 && code < 500; // 4xx 也算"可达"
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    @Override
    public boolean isModified() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        return !backendUrlField.getText().trim().equals(s.backendUrl)
            || !webAppTokenField.getText().trim().equals(s.webAppToken);
    }

    @Override
    public void apply() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        s.backendUrl = backendUrlField.getText().trim();
        s.webAppToken = webAppTokenField.getText().trim();
        // 通知订阅方（面板）重新加载
        ApplicationManager.getApplication().getMessageBus().syncPublisher(
            WebAppSettingsState.SETTINGS_CHANGED).settingsChanged();
    }

    @Override
    public void reset() {
        WebAppSettingsState s = WebAppSettingsState.getInstance();
        backendUrlField.setText(s.backendUrl);
        webAppTokenField.setText(s.webAppToken);
        refreshAccount();
        statusLabel.setText(" ");
    }
}
