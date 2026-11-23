package com.webapp.plugin.toolwindow;

import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowFactory;
import org.jetbrains.annotations.NotNull;

/**
 * 创建 WebApp 工具窗口内容，并把面板生命周期挂到 Project 的 Disposer 上。
 */
public final class WebAppToolWindowFactory implements ToolWindowFactory {

    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        WebAppPanel panel = new WebAppPanel(project);
        Disposer.register(project, panel);

        // 标题栏刷新按钮：自定义 Action 直接调用面板 reload()（不复用 IDE 全局 Refresh action）。
        AnAction refresh = new AnAction("刷新", "重新加载 WebApp 页面",
            com.intellij.icons.AllIcons.Actions.Refresh) {
            @Override
            public void actionPerformed(@NotNull AnActionEvent e) {
                panel.reload();
            }
        };
        toolWindow.setTitleActions(java.util.List.of(refresh));

        // 内容 displayName 置空：工具窗口 id 已是 "WebApp"，再给内容加同名标签会在
        // 窗口内顶部多出一个 "WebApp" tab（两个 WebApp 重复）。单内容空名称时
        // IDE 不渲染内部标签栏，只保留侧边栏的工具窗口标题。
        toolWindow.getContentManager().addContent(
            toolWindow.getContentManager().getFactory().createContent(panel, "", false)
        );
    }
}
