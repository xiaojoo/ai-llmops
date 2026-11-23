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
    private JComponent loadedCard;

    public LoadStateOverlay(Runnable onReload, Supplier<String> urlSupplier) {
        this.onReload = onReload;
        this.urlSupplier = urlSupplier;
        root.add(loadingCard("正在连接服务器..."), CARD_LOADING);
        root.add(loadingCard("连接中，请稍候..."), CARD_CONNECTING);
        loadedCard = new JBPanel<>();
        root.add(loadedCard, CARD_LOADED);
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

    /**
     * 设置 LOADED 状态显示的组件（浏览器）。在面板初始化时调用。
     * 幂等：二次调用先移除旧 holder，避免重复 add 同一 CardLayout 约束。
     */
    public void setLoadedContent(JComponent component) {
        if (loadedCard != null) {
            root.remove(loadedCard);
        }
        javax.swing.JPanel holder = new javax.swing.JPanel(new java.awt.BorderLayout());
        holder.add(component, java.awt.BorderLayout.CENTER);
        root.add(holder, CARD_LOADED);
        loadedCard = holder;
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
}
