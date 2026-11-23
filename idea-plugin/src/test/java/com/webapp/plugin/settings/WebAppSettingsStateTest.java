package com.webapp.plugin.settings;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WebAppSettingsStateTest {

    @Test
    void defaultsMatchSpec() {
        WebAppSettingsState s = new WebAppSettingsState();
        assertEquals("http://localhost:5000", s.backendUrl);
        assertEquals("M0GEcQmJvGMCN5ou", s.webAppToken);
        assertEquals("", s.authToken);
        assertEquals("", s.email);
    }

    @Test
    void loggedInState() {
        WebAppSettingsState s = new WebAppSettingsState();
        assertFalse(s.isLoggedIn());
        s.authToken = "abc123";
        assertTrue(s.isLoggedIn());
        s.clearAuth();
        assertFalse(s.isLoggedIn());
    }

    @Test
    void stateRoundTrip() {
        WebAppSettingsState s = new WebAppSettingsState();
        s.backendUrl = "https://staging.example.com";
        s.webAppToken = "other-token";
        s.authToken = "token-xyz";
        s.email = "user@example.com";
        WebAppSettingsState loaded = new WebAppSettingsState();
        loaded.loadState(s.getState());
        assertEquals("https://staging.example.com", loaded.backendUrl);
        assertEquals("other-token", loaded.webAppToken);
        assertEquals("token-xyz", loaded.authToken);
        assertEquals("user@example.com", loaded.email);
    }

    @Test
    void loadStateToleratesNullNewFields() {
        // 兼容旧版持久化：新字段缺失时回退默认值
        WebAppSettingsState s = new WebAppSettingsState();
        s.serverUrl = null;
        s.path = null;
        s.backendUrl = null;
        s.webAppToken = null;
        s.authToken = null;
        s.email = null;
        WebAppSettingsState loaded = new WebAppSettingsState();
        loaded.loadState(s.getState());
        assertEquals("http://localhost:5000", loaded.backendUrl);
        assertEquals("M0GEcQmJvGMCN5ou", loaded.webAppToken);
        assertEquals("", loaded.authToken);
        assertEquals("", loaded.email);
    }
}
