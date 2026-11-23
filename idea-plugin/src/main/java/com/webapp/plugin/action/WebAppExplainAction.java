package com.webapp.plugin.action;

/** 编辑器右键菜单：解释选中代码（只展示说明，不替换）。 */
public final class WebAppExplainAction extends WebAppCodeActionBase {
    @Override
    protected String actionName() {
        return "explain";
    }

    @Override
    protected String actionLabel() {
        return "解释";
    }

    @Override
    protected boolean replaceSemantics() {
        return false;
    }
}
