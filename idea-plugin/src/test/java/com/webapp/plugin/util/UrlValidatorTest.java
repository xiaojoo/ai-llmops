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
