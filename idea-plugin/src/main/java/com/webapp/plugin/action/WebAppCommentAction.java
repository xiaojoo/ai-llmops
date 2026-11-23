package com.webapp.plugin.action;

/** 编辑器右键菜单：为选中代码添加注释（替换选中内容）。 */
public final class WebAppCommentAction extends WebAppCodeActionBase {
    @Override
    protected String actionName() {
        return "comment";
    }

    @Override
    protected String actionLabel() {
        return "注释";
    }
}
