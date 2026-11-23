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
            // LinkageError 覆盖 NoClassDefFoundError：JCEF 类不可加载时安全降级
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
