package com.webapp.plugin.action;

import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.command.WriteCommandAction;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.editor.SelectionModel;
import com.intellij.openapi.progress.ProgressManager;
import com.intellij.openapi.progress.Task;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.Messages;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowManager;
import com.webapp.plugin.bridge.WebAppBridge;
import com.webapp.plugin.toolwindow.WebAppPanel;
import com.google.gson.JsonObject;
import org.jetbrains.annotations.NotNull;

/**
 * 编辑器右键菜单 AI 代码操作（优化/解释/注释/自定义）——对齐 VS Code 插件行为：
 * 1. 读取当前编辑器选中文本
 * 2. 检查登录态（未登录提示先到 WebApp 窗口登录）
 * 3. optimize/comment/explain → 调后端 code_action → 弹窗确认 → 替换选中内容（可 Undo）
 * 4. custom → 选中文本填入聊天输入框（setComposerText），不发送
 */
public abstract class WebAppCodeActionBase extends AnAction {

    private static final Logger LOG = Logger.getInstance(WebAppCodeActionBase.class);

    /** 操作类型：optimize / explain / comment；custom 单独一个 action 类。 */
    protected abstract String actionName();

    /** 操作中文标签（弹窗文案用）。 */
    protected abstract String actionLabel();

    /** 是否 replace 语义（explain 只展示不替换）。 */
    protected boolean replaceSemantics() {
        return true;
    }

    @Override
    public @NotNull ActionUpdateThread getActionUpdateThread() {
        return ActionUpdateThread.BGT;
    }

    @Override
    public void update(@NotNull AnActionEvent e) {
        // 仅在编辑器有选中文本时显示
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
        SelectionModel selection = editor.getSelectionModel();
        String selected = selection.getSelectedText();
        if (selected == null || selected.isBlank()) {
            Messages.showInfoMessage("请先在编辑器中选中代码内容", "WebApp AI");
            return;
        }

        // 登录校验（与聊天功能共用登录态）
        if (!com.webapp.plugin.settings.WebAppSettingsState.getInstance().isLoggedIn()) {
            int go = Messages.showYesNoDialog(
                project,
                "WebApp AI 操作需要先登录。是否打开 WebApp 会话窗口登录?",
                "WebApp AI",
                "去登录",
                "取消",
                Messages.getWarningIcon());
            if (go == Messages.YES) {
                openToolWindow(project);
            }
            return;
        }

        final String code = selected;
        final String language = languageName(editor, e.getData(CommonDataKeys.VIRTUAL_FILE));

        // 后台调用（网络请求不阻塞 EDT）
        ProgressManager.getInstance().run(new Task.Modal(project, "WebApp AI：" + actionLabel() + "选中代码…", true) {
            private JsonObject result;

            @Override
            public void run(@NotNull com.intellij.openapi.progress.ProgressIndicator indicator) {
                WebAppBridge bridge = findBridge(project);
                if (bridge == null) {
                    result = null;
                    return;
                }
                result = bridge.codeAction(actionName(), code, language);
            }

            @Override
            public void onSuccess() {
                if (result == null) {
                    Messages.showErrorDialog(
                        "WebApp AI：" + actionLabel() + "请求失败（请检查后端服务与登录状态）", "WebApp AI");
                    return;
                }
                String outCode = result.has("code") && result.get("code").isJsonPrimitive()
                    ? result.get("code").getAsString() : "";
                String explanation = result.has("explanation") && result.get("explanation").isJsonPrimitive()
                    ? result.get("explanation").getAsString() : "";
                String content = (outCode != null && !outCode.isBlank()) ? outCode : (explanation == null ? "" : explanation);

                if (content == null || content.isBlank()) {
                    Messages.showErrorDialog("WebApp AI：" + actionLabel() + "未返回结果，请重试", "WebApp AI");
                    return;
                }

                // explain：只展示（打开一个临时编辑器预览），不替换
                if (!replaceSemantics()) {
                    showExplanation(project, explanation == null ? "" : explanation);
                    return;
                }

                // 优化/注释：弹窗询问是否替换
                String summary = content.length() > 120 ? content.substring(0, 120) + "…" : content;
                int choice = Messages.showYesNoDialog(
                    project,
                    "WebApp AI " + actionLabel() + "结果已生成：\n\n" + summary + "\n\n是否替换选中内容?",
                    "WebApp AI " + actionLabel(),
                    "替换",
                    "取消",
                    Messages.getQuestionIcon());
                if (choice != Messages.YES) return;

                replaceSelection(project, editor, content);
            }
        });
    }

    /** 替换选中范围（WriteCommandAction，支持 Undo）。 */
    private void replaceSelection(Project project, Editor editor, String newText) {
        int start = editor.getSelectionModel().getSelectionStart();
        int end = editor.getSelectionModel().getSelectionEnd();
        com.intellij.openapi.command.WriteCommandAction.writeCommandAction(project)
            .withName("WebApp AI 替换")
            .run(() -> editor.getDocument().replaceString(start, end, newText));
    }

    /** explain 结果：在临时编辑器打开 Markdown 说明（不替换代码）。 */
    private void showExplanation(Project project, String explanation) {
        ApplicationManager.getApplication().invokeLater(() -> {
            try {
                com.intellij.openapi.fileEditor.FileEditorManager.getInstance(project)
                    .openTextEditor(new com.intellij.openapi.fileEditor.OpenFileDescriptor(
                        project,
                        com.intellij.openapi.vfs.LocalFileSystem.getInstance()
                            .findFileByIoFile(java.io.File.createTempFile("webapp-explain-", ".md"))),
                        true);
            } catch (Exception ex) {
                LOG.warn("WebApp explain preview failed", ex);
                Messages.showMessageDialog(project, explanation, "WebApp AI 解释", Messages.getInformationIcon());
            }
        });
    }

    /** 打开 WebApp 工具窗口（登录提示用）。 */
    private void openToolWindow(Project project) {
        ApplicationManager.getApplication().invokeLater(() -> {
            ToolWindow tw = ToolWindowManager.getInstance(project).getToolWindow("WebApp");
            if (tw != null) tw.activate(null);
        });
    }

    /** 从工具窗口内容里找到 WebAppPanel → bridge。 */
    public static WebAppBridge findBridge(Project project) {
        ToolWindow tw = ToolWindowManager.getInstance(project).getToolWindow("WebApp");
        if (tw == null) return null;
        var contents = tw.getContentManager().getContents();
        for (var c : contents) {
            var comp = c.getComponent();
            if (comp instanceof WebAppPanel panel) {
                return panel.getBridge();
            }
            // SimpleToolWindowPanel 包装：递归查找
            WebAppPanel panel = findPanel(comp);
            if (panel != null) return panel.getBridge();
        }
        return null;
    }

    private static WebAppPanel findPanel(java.awt.Component c) {
        if (c instanceof WebAppPanel panel) return panel;
        if (c instanceof java.awt.Container container) {
            for (var child : container.getComponents()) {
                WebAppPanel found = findPanel(child);
                if (found != null) return found;
            }
        }
        return null;
    }

    /** 编辑器语言 id → 后端提示词语言名（兜底用文件扩展名）。 */
    private static String languageName(Editor editor, VirtualFile file) {
        if (file != null) {
            String langId = file.getFileType().getName();
            if (langId != null && !langId.isBlank() && !"PLAIN_TEXT".equalsIgnoreCase(langId)) {
                return langId;
            }
        }
        String name = file != null ? file.getName() : "";
        int dot = name.lastIndexOf('.');
        return dot >= 0 ? name.substring(dot + 1) : "";
    }
}
