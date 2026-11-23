package com.webapp.plugin.toolwindow;

import com.webapp.plugin.toolwindow.LoadStateOverlay.LoadState;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

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

    @Test
    void loadedContentSwapsCard() {
        LoadStateOverlay overlay = new LoadStateOverlay(() -> { }, () -> "http://x");
        javax.swing.JPanel fake = new javax.swing.JPanel();
        overlay.setLoadedContent(fake);
        overlay.setState(LoadState.LOADED);
        // LOADED 卡片持有 fake 组件
        assertNotNull(fake.getParent());
    }
}
