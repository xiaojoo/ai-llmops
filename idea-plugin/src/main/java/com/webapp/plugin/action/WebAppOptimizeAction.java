package com.webapp.plugin.action;

/** 编辑器右键菜单：优化选中代码（替换选中内容）。 */
public final class WebAppOptimizeAction extends WebAppCodeActionBase {
    @Override
    protected String actionName() {
        return "optimize";
    }

    @Override
    protected String actionLabel() {
        return "优化";
    }
}
