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
