/**
 * 编辑器右键菜单 AI 操作（优化/解释/注释/自定义）：
 * 1. 读取 activeTextEditor 选中文本
 * 2. 检查登录态（未登录提示先到聊天窗口登录）
 * 3. 调后端 POST /web_apps/{token}/code_action
 * 4. 弹窗询问是否替换 → 确认后 editor.edit() 替换选中范围（可 Undo）
 *
 * "自定义"：不调后端，直接把选中文本填入聊天输入框（webview 侧 setComposerText），不发送。
 */
import * as vscode from 'vscode'
import { WebAppApiClient } from './api/client'
import { StateStore } from './state'

export type CodeActionKind = 'optimize' | 'explain' | 'comment'

const ACTION_LABEL: Record<CodeActionKind, string> = {
  optimize: '优化',
  explain: '解释',
  comment: '注释',
}

/** 编辑器语言 id → 后端提示词语言名（粗略映射，兜底用文件扩展名） */
function languageName(editor: vscode.TextEditor): string {
  const langId = editor.document.languageId
  if (langId && langId !== 'plaintext') return langId
  const ext = (editor.document.fileName.split('.').pop() || '').toLowerCase()
  return ext || ''
}

/** 获取当前选中文本；无选中/无编辑器返回 null */
function selectedText(): { editor: vscode.TextEditor; text: string } | null {
  const editor = vscode.window.activeTextEditor
  if (!editor) return null
  const selection = editor.selection
  if (selection.isEmpty) return null
  const text = editor.document.getText(selection)
  if (!text || !text.trim()) return null
  return { editor, text }
}

/** 替换选中范围（返回成功与否）。editor.edit 是异步的（undo 栈自动处理）。 */
async function replaceSelection(editor: vscode.TextEditor, newText: string): Promise<boolean> {
  return editor.edit((editBuilder) => {
    editBuilder.replace(editor.selection, newText)
  })
}

/**
 * 执行一个 AI 代码操作。由 extension.ts 注册的命令回调调用。
 * @param setComposerText 把文本填入聊天输入框（"自定义"操作使用）
 */
export async function runCodeAction(
  state: StateStore,
  action: CodeActionKind,
  setComposerText: (text: string) => void,
): Promise<void> {
  const sel = selectedText()
  if (!sel) {
    void vscode.window.showInformationMessage('请先在编辑器中选中代码内容')
    return
  }
  const { editor, text } = sel

  // 登录校验（与聊天功能共用登录态）
  const authToken = await state.authToken()
  if (!authToken) {
    const go = await vscode.window.showWarningMessage(
      'WebApp AI 操作需要先登录。是否打开会话窗口登录?',
      { modal: true },
      '去登录',
    )
    if (go === '去登录') {
      await vscode.commands.executeCommand('webapp-chat.focus')
    }
    return
  }

  const webAppToken = state.webAppToken()
  if (!webAppToken) {
    void vscode.window.showErrorMessage('未配置 WebApp Token（设置 webapp-chat.defaultWebAppToken）')
    return
  }

  const label = ACTION_LABEL[action]
  const status = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `WebApp AI：正在${label}选中代码…`,
      cancellable: false,
    },
    async () => {
      const client = new WebAppApiClient(state.backendUrl())
      const result = await client.codeAction(webAppToken, authToken, action, text, languageName(editor))
      if (!result) throw new Error('请求失败（请检查后端服务与登录状态）')
      return result
    },
  )

  // explain 返回 explanation 文本（不替换）；optimize/comment 返回 code（可替换）
  const code = typeof status['code'] === 'string' ? status['code'] : ''
  const explanation = typeof status['explanation'] === 'string' ? status['explanation'] : ''
  const content = code || explanation

  if (!content.trim()) {
    void vscode.window.showErrorMessage(`WebApp AI：${label}未返回结果，请重试`)
    return
  }

  if (action === 'explain') {
    // 解释：只展示，不替换
    const doc = await vscode.workspace.openTextDocument({
      language: 'markdown',
      content: `# WebApp AI 解释\n\n${explanation}`,
    })
    await vscode.window.showTextDocument(doc, { preview: true, viewColumn: vscode.ViewColumn.Beside })
    return
  }

  // 优化/注释：弹窗询问是否替换
  const summary = content.length > 120 ? content.slice(0, 120) + '…' : content
  const choice = await vscode.window.showWarningMessage(
    `WebApp AI ${label}结果已生成：\n\n${summary}\n\n是否替换选中内容?`,
    { modal: true },
    '替换',
    '取消',
  )
  if (choice !== '替换') return

  const ok = await replaceSelection(editor, content)
  if (ok) {
    void vscode.window.showInformationMessage(`已用 WebApp AI ${label}结果替换选中内容`)
  } else {
    void vscode.window.showErrorMessage('替换失败（文档可能已被修改）')
  }
}

/**
 * "自定义"：把选中文本填入聊天输入框（不发送）。
 * 用户可在输入框里补充指令后手动发送。
 */
export async function runCustomFill(state: StateStore, setComposerText: (text: string) => void): Promise<void> {
  const sel = selectedText()
  if (!sel) {
    void vscode.window.showInformationMessage('请先在编辑器中选中代码内容')
    return
  }
  const authToken = await state.authToken()
  if (!authToken) {
    const go = await vscode.window.showWarningMessage(
      'WebApp AI 操作需要先登录。是否打开会话窗口登录?',
      { modal: true },
      '去登录',
    )
    if (go === '去登录') {
      await vscode.commands.executeCommand('webapp-chat.focus')
    }
    return
  }
  setComposerText(sel.text)
  await vscode.commands.executeCommand('webapp-chat.focus')
  void vscode.window.showInformationMessage('选中内容已填入输入框，可补充指令后发送')
}
