/**
 * VS Code 扩展入口（对应 Java 插件 plugin.xml 的扩展点注册）。
 * - contributes.views 侧边栏 "WebApp 会话" webview（package.json 声明）
 * - 命令 webapp-chat.focus：聚焦侧边栏视图
 * - 编辑器右键菜单 AI 操作：优化/解释/注释/自定义（webapp-chat.codeAction.*）
 */
import * as vscode from 'vscode'
import { runCodeAction, runCustomFill } from './codeActions'
import { StateStore } from './state'
import { WebAppChatViewProvider } from './webview'

export function activate(context: vscode.ExtensionContext): void {
  const backendUrl =
    vscode.workspace.getConfiguration('webapp-chat').get<string>('backendUrl') || 'http://localhost:5000'
  console.log(`[webapp-chat] extension activated (backendUrl=${backendUrl})`)

  const state = new StateStore(context)
  const viewProvider = new WebAppChatViewProvider(context)

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      WebAppChatViewProvider.viewType,
      viewProvider,
      // 不设 retainContextWhenHidden：VS Code 新版(1.100+)在保留 webview 上下文时
      // 可能触发 "Could not register service worker" 加载错误；
      // 隐藏后重建页面，会话/登录态由 StateStore(SecretStorage/globalState) 持久化可恢复。
    ),
  )

  context.subscriptions.push(
    vscode.commands.registerCommand('webapp-chat.focus', () => {
      void vscode.commands.executeCommand('webappSession.focus')
    }),
  )

  // 把 WebApp 视图移到右侧辅助边栏（Secondary Side Bar）。
  // VS Code 没有官方 API 在 package.json 里声明视图位置，移动视图只能靠用户拖拽
  // 或内置命令；这里先聚焦视图再尝试内置命令，命令不可用时提示手动操作。
  context.subscriptions.push(
    vscode.commands.registerCommand('webapp-chat.moveToSecondarySideBar', async () => {
      await vscode.commands.executeCommand('webappSession.focus')
      try {
        await vscode.commands.executeCommand('workbench.action.moveViewToSecondarySideBar')
      } catch {
        vscode.window.showInformationMessage(
          '请手动移动：右键 "WebApp" 视图标题 → "Move View into Secondary Side Bar"，或把标题拖到右侧',
        )
      }
    }),
  )

  // ===== 编辑器右键菜单 AI 操作 =====
  const setComposerText = (text: string): void => viewProvider.setComposerText(text)
  context.subscriptions.push(
    vscode.commands.registerCommand('webapp-chat.codeAction.optimize', () =>
      void runCodeAction(state, 'optimize', setComposerText),
    ),
    vscode.commands.registerCommand('webapp-chat.codeAction.explain', () =>
      void runCodeAction(state, 'explain', setComposerText),
    ),
    vscode.commands.registerCommand('webapp-chat.codeAction.comment', () =>
      void runCodeAction(state, 'comment', setComposerText),
    ),
    vscode.commands.registerCommand('webapp-chat.codeAction.custom', () =>
      void runCustomFill(state, setComposerText),
    ),
  )
}

export function deactivate(): void {
  // 无全局资源需要释放
}
