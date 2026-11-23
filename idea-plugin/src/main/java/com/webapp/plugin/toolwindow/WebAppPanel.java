package com.webapp.plugin.toolwindow;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.ui.jcef.JBCefBrowser;
import com.webapp.plugin.settings.WebAppSettingsListener;
import com.webapp.plugin.settings.WebAppSettingsState;
import com.webapp.plugin.toolwindow.LoadStateOverlay.LoadState;
import com.webapp.plugin.util.JcefSupport;
import org.jetbrains.annotations.NotNull;

import javax.swing.JComponent;
import javax.swing.SwingUtilities;
import java.awt.Desktop;

/**
 * 工具窗口内容：JCEF 浏览器 + 状态覆盖层。
 * 生命周期：随 Project 注册到 Disposer，dispose() 释放浏览器。
 */
public final class WebAppPanel extends com.intellij.openapi.ui.SimpleToolWindowPanel implements Disposable {

    private static final Logger LOG = Logger.getInstance(WebAppPanel.class);

    private final Project project;
    private JBCefBrowser browser;
    private LoadStateOverlay overlay;
    private com.webapp.plugin.bridge.WebAppBridge bridge;
    /** 当前注册的 CefLoadHandler；dispose 时从（可能共享的）CefClient 上移除，防止泄漏与串扰。 */
    private org.cef.handler.CefLoadHandler loadHandler;
    /**
     * 逻辑加载状态：随 setLoadState 同步更新（包括非 EDT 线程）。
     * overlay.getState() 只在 EDT 上随 setState 更新，CEF 回调线程读取会滞后，
     * 故加载事件判定以本字段为准。
     */
    private volatile LoadState currentState = LoadState.LOADING;

    /** 加载看门狗：初始加载长时间无结果时切到网络错误卡片，避免永久卡在"正在连接服务器..."。 */
    private javax.swing.Timer loadWatchdog;
    private static final int LOAD_WATCHDOG_MS = 20000;

    public WebAppPanel(@NotNull Project project) {
        super(true, true);
        this.project = project;
        if (JcefSupport.checkAvailability() == JcefSupport.Status.AVAILABLE) {
            initBrowser();
        } else {
            showFallback();
        }
        // 设置变更传播：WebAppSettingsConfigurable.apply() 发布后自动 reload。
        // connect(this) 把订阅绑定到面板生命周期，dispose 时自动取消订阅。
        ApplicationManager.getApplication().getMessageBus().connect(this)
            .subscribe(WebAppSettingsState.SETTINGS_CHANGED, new WebAppSettingsListener() {
                @Override
                public void settingsChanged() {
                    reload();
                }
            });
    }

    private void initBrowser() {
        browser = new JBCefBrowser();
        // 加载本地单文件 Web UI（file://）。JS/CSS 已全部内联进 index.html，
        // 无外部 module 请求——file:// 下内联脚本可正常执行。
        // （自定义 scheme 下 Chromium 禁止非 standard scheme 执行内联脚本，已弃用）
        overlay = new LoadStateOverlay(this::reload, this::currentUrl);
        overlay.setLoadedContent(browser.getComponent());
        bridge = new com.webapp.plugin.bridge.WebAppBridge(browser, project);
        setContent(overlay.getComponent());
        overlay.setState(LoadState.LOADING);
        // 顺序：先强制创建 CEF 浏览器（createImmediately），再经 JBCefClient 注册加载监听
        // （需要 getCefBrowser() 非空才能按浏览器绑定），最后导航。
        // 浏览器未创建时 loadURL 只写入 LoadDeferrer（延迟导航），部分环境（IPGP runIde 沙箱
        // 2024.2）defer 回调不触发 → 永远不加载，故先创建再导航。
        browser.createImmediately();
        registerLoadHandler();
        browser.loadURL(localUiUrl());
        // console 监听需要 getCefBrowser() 已创建（loadURL 后），放这里
        registerConsoleListener();
        startLoadWatchdog();
    }

    /** 监听页面 console（捕获 JS 错误，便于诊断）。 */
    private void registerConsoleListener() {
        browser.getJBCefClient().addDisplayHandler(new org.cef.handler.CefDisplayHandlerAdapter() {
            @Override
            public boolean onConsoleMessage(org.cef.browser.CefBrowser b,
                                            org.cef.CefSettings.LogSeverity level,
                                            String message, String source, int line) {
                if (b != null && b.equals(browser.getCefBrowser())
                    && level == org.cef.CefSettings.LogSeverity.LOGSEVERITY_ERROR) {
                    LOG.warn("WebApp JS console error: " + message + " @ " + source + ":" + line);
                }
                return false;
            }
        }, browser.getCefBrowser());
    }

    private void showFallback() {
        JcefSupport.Status status = JcefSupport.checkAvailability();
        if (status == JcefSupport.Status.AVAILABLE) {
            initBrowser();
            return;
        }
        JComponent fallback = JcefSupport.buildFallbackPanel(
            Desktop.getDesktop(),
            currentUrl(),
            this::reload
        );
        setContent(fallback);
    }

    /** 本地单文件 Web UI 的 file:// URL（解压插件 resources/web-ui）。 */
    private static String localUiUrl() {
        try {
            return com.webapp.plugin.util.WebUiResourceLoader.extractAndGetIndexUrl();
        } catch (Exception e) {
            LOG.warn("WebApp web-ui 资源解压失败", e);
            return "";
        }
    }

    public String currentUrl() {
        return localUiUrl();
    }

    public void reload() {
        if (browser != null) {
            browser.loadURL(currentUrl());
            startLoadWatchdog();
        } else {
            showFallback();
        }
    }

    /** 启动（或重启）加载看门狗：20s 内仍处于加载态则切到网络错误卡片（可手动重试）。 */
    private void startLoadWatchdog() {
        if (loadWatchdog != null) {
            loadWatchdog.stop();
        }
        loadWatchdog = new javax.swing.Timer(LOAD_WATCHDOG_MS, e -> {
            LoadState s = getCurrentLoadState();
            if (s == LoadState.LOADING || s == LoadState.CONNECTING) {
                LOG.warn("WebApp load watchdog: 20s 内未完成加载（state=" + s + "），切换网络错误态");
                setLoadState(LoadState.NETWORK_ERROR);
            }
        });
        loadWatchdog.setRepeats(false);
        loadWatchdog.start();
    }

    public JBCefBrowser getBrowser() {
        return browser;
    }

    /** 供编辑器右键菜单 AnAction 调用（自定义填入输入框 / codeAction）。 */
    public com.webapp.plugin.bridge.WebAppBridge getBridge() {
        return bridge;
    }

    /**
     * 注册 CEF 加载状态监听。
     * <p>错误闩锁：onLoadError 置 NETWORK_ERROR 后，随后的 onLoadingStateChange(false)/
     * onLoadEnd 不得覆盖为 LOADED（CEF 失败加载同样触发 isLoading=false）。
     * 每个回调先按 browser/main-frame 过滤，避免共享 CefClient 下其他面板的加载事件串扰。
     */
    private void registerLoadHandler() {
        if (browser == null) {
            return;
        }
        org.cef.handler.CefLoadHandler handler = new org.cef.handler.CefLoadHandler() {
            /** 本次导航是否已失败；onLoadStart 重置。 */
            private volatile boolean loadFailed;

            private boolean isOurs(org.cef.browser.CefBrowser b) {
                JBCefBrowser current = browser;
                return b != null && current != null && b.equals(current.getCefBrowser());
            }

            private boolean isOurs(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f) {
                return isOurs(b) && f != null && f.isMain();
            }

            @Override
            public void onLoadingStateChange(org.cef.browser.CefBrowser b, boolean isLoading,
                                             boolean canGoBack, boolean canGoForward) {
                if (!isOurs(b)) {
                    return;
                }
                if (!isLoading && !loadFailed) {
                    // CEF 时序：onLoadingStateChange(false) 在 onLoadEnd/onLoadError 之后回调，
                    // 且 HTTP 状态码错误（401/403/5xx → AUTH_ERROR/WEBAPP_ERROR）不会置位
                    // loadFailed——直接置 LOADED 会覆盖错误卡片。仅当仍处于 LOADING/CONNECTING
                    // 时才提升为 LOADED。
                    LoadState current = getCurrentLoadState();
                    if (current == LoadState.LOADING || current == LoadState.CONNECTING) {
                        setLoadState(LoadState.LOADED);
                    }
                }
            }

            @Override
            public void onLoadStart(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                    org.cef.network.CefRequest.TransitionType t) {
                if (!isOurs(b, f)) {
                    return;
                }
                loadFailed = false;
                LOG.info("WebApp JCEF load start: url=" + b.getURL());
                setLoadState(LoadState.LOADING);
            }

            @Override
            public void onLoadEnd(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                  int httpStatusCode) {
                if (!isOurs(b, f)) {
                    return;
                }
                if (loadFailed) {
                    return;
                }
                // 按状态码细分：401/403 → AUTH_ERROR，5xx → WEBAPP_ERROR，其余 → LOADED
                if (httpStatusCode == 401 || httpStatusCode == 403) {
                    setLoadState(LoadState.AUTH_ERROR);
                } else if (httpStatusCode >= 500) {
                    setLoadState(LoadState.WEBAPP_ERROR);
                } else {
                    setLoadState(LoadState.LOADED);
                    // 页面加载完成：注入 JS↔Java 桥（window.agentChatHost）
                    if (bridge != null) {
                        bridge.installJsBridge();
                    }
                }
            }

            @Override
            public void onLoadError(org.cef.browser.CefBrowser b, org.cef.browser.CefFrame f,
                                    org.cef.handler.CefLoadHandler.ErrorCode errorCode,
                                    String errorText, String failedUrl) {
                if (!isOurs(b, f)) {
                    return;
                }
                // ERR_ABORTED 是导航被取消/替换（如 Vue Router 重定向、OAuth 跳转），
                // 不是连接失败——忽略它，等待后续导航事件（onLoadStart/onLoadEnd）
                if (errorCode == org.cef.handler.CefLoadHandler.ErrorCode.ERR_ABORTED) {
                    LOG.info("WebApp JCEF navigation aborted (expected): url=" + failedUrl);
                    return;
                }
                loadFailed = true;
                LOG.warn("WebApp JCEF load error: code=" + errorCode
                    + ", text=" + errorText + ", url=" + failedUrl
                    + ", settingsUrl=" + currentUrl());
                setLoadState(LoadState.NETWORK_ERROR);
            }
        };
        this.loadHandler = handler;
        // 必须用 JBCefClient.addLoadHandler(handler, browser)：JBCefClient 用 HandlerSupport 按
        // 浏览器管理 handler 列表，原始 CefClient 的单槽被 JBCefClient 分发器占用；直接调
        // getCefClient().addLoadHandler() 会顶掉分发器导致任何加载事件都不再回调。
        browser.getJBCefClient().addLoadHandler(handler, browser.getCefBrowser());
    }

    /** 更新覆盖层状态；CEF 回调线程非 EDT，需派发到 EDT 再改 Swing 组件。 */
    public void setLoadState(LoadState state) {
        // 同步记录逻辑状态（CEF 线程可即时读取），再派发到 EDT 更新 UI
        currentState = state;
        // 离开加载态后停止看门狗
        if (state != LoadState.LOADING && state != LoadState.CONNECTING && loadWatchdog != null) {
            loadWatchdog.stop();
        }
        if (overlay == null) {
            return;
        }
        Runnable task = () -> overlay.setState(state);
        if (SwingUtilities.isEventDispatchThread()) {
            task.run();
        } else {
            SwingUtilities.invokeLater(task);
        }
    }

    /** 供 CEF 加载回调线程读取当前逻辑状态（与 EDT 派发解耦，无滞后）。 */
    private LoadState getCurrentLoadState() {
        return currentState;
    }

    @Override
    public void dispose() {
        if (loadWatchdog != null) {
            loadWatchdog.stop();
            loadWatchdog = null;
        }
        if (bridge != null) {
            Disposer.dispose(bridge);
            bridge = null;
        }
        if (browser != null) {
            if (loadHandler != null) {
                // 与注册方式对应：JBCefClient 按浏览器移除（原始 CefClient 无参 removeLoadHandler
                // 会移除 JBCefClient 的分发器，破坏同 client 上其他浏览器的回调）
                browser.getJBCefClient().removeLoadHandler(loadHandler, browser.getCefBrowser());
                loadHandler = null;
            }
            Disposer.dispose(browser);
            browser = null;
        }
    }
}
