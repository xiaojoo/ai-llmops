package com.webapp.plugin.action;

import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.Messages;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowManager;
import com.webapp.plugin.bridge.WebAppBridge;
import org.jetbrains.annotations.NotNull;

/**
 * 编辑器右键菜单"自定义"：把选中代码填入 WebApp 聊天输入框（不自动发送），
 * 用户可在输入框里补充指令后手动发送——与 VS Code 插件行为一致。
 */
public final class WebAppCustomFillAction extends AnAction {

    @Override
    public @NotNull ActionUpdateThread getActionUpdateThread() {
        return ActionUpdateThread.BGT;
    }

    @Override
    public void update(@NotNull AnActionEvent e) {
        Editor editor = e.getData(CommonDataKeys.EDITOR);
        boolean hasSelection = editor != null
            && editor.getSelectionModel() != null
            && !editor.getSelectionModel().getSelectedText().isBlank();
        e.getPresentation().setEnabledAndVisible(hasSelection);
    }

    @Override
    public void actionPerformed(@NotNull AnActionEvent e) {
        Project project = e.getProject();
        Editor editor = e.getData(CommonDataKeys.EDITOR);
        if (project == null || editor == null) return;
        String selected = editor.getSelectionModel().getSelectedText();
        if (selected == null || selected.isBlank()) {
            Messages.showInfoMessage("请先在编辑器中选中代码内容", "WebApp AI");
            return;
        }
        if (!com.webapp.plugin.settings.WebAppSettingsState.getInstance().isLoggedIn()) {
            int go = Messages.showYesNoDialog(
                project,
                "WebApp AI 操作需要先登录。是否打开 WebApp 会话窗口登录?",
                "WebApp AI",
                "去登录",
                "取消",
                Messages.getWarningIcon());
            if (go == Messages.YES) {
                ApplicationManager.getApplication().invokeLater(() -> {
                    ToolWindow tw = ToolWindowManager.getInstance(project).getToolWindow("WebApp");
                    if (tw != null) tw.activate(null);
                });
            }
            return;
        }
        WebAppBridge bridge = WebAppCodeActionBase.findBridge(project);
        if (bridge == null) {
            Messages.showWarningDialog(
                "未找到 WebApp 会话窗口，请先打开一次 WebApp 窗口再使用该功能", "WebApp AI");
            return;
        }
        bridge.setComposerText(selected);
        // 打开并激活 WebApp 窗口，让用户看到填入的内容
        ApplicationManager.getApplication().invokeLater(() -> {
            ToolWindow tw = ToolWindowManager.getInstance(project).getToolWindow("WebApp");
            if (tw != null) tw.activate(null);
        });
        Messages.showInfoMessage("选中内容已填入输入框，可补充指令后发送", "WebApp AI");
    }
}
