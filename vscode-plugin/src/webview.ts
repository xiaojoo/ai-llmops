/**
 * Webview 提供者（对应 Java 的 WebAppToolWindowFactory + WebAppPanel）。
 * 加载单文件前端产物（dist/media/index.html，由 scripts/build-webview.js 生成），
 * 并实现 JS↔宿主桥：webview 的 agentChatHost 调用 → bridge.handle → 回包；
 * bridge 的 pushEvent → webview.postMessage（bootstrap 脚本转发给 __agentChatEvent）。
 */
import * as fs from 'node:fs'
import * as vscode from 'vscode'
import { Bridge } from './bridge'
import { StateStore } from './state'

export class WebAppChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'webappSession'

  private view: vscode.WebviewView | undefined
  private bridge: Bridge | undefined
  private disposed = false
  /** 诊断输出通道：SSE 粗粒度 recv / 本地工具看门狗等日志（对应 IDEA 版 idea.log 的 WebApp 日志） */
  private readonly output: vscode.OutputChannel

  constructor(private readonly context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel('WebApp Chat')
    context.subscriptions.push(this.output)
  }

  /**
   * 把文本填入聊天输入框（右键菜单"自定义"用）：复用宿主→webview 事件通道，
   * 前端 AgentChatEmbed 的 handleEvent 收到 setComposerText 后回填输入框，不发送。
   */
  setComposerText(text: string): void {
    if (this.view && !this.disposed) {
      void this.view.webview.postMessage({ type: 'setComposerText', data: { text } })
    }
  }

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    console.log('[webapp-chat] resolveWebviewView')
    this.view = webviewView
    this.disposed = false
    // 去掉侧边栏视图标题栏的文字（VS Code 原生 header 仍会渲染一条窄栏，无法完全移除）
    webviewView.title = ''

    const webview = webviewView.webview
    webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'media')],
    }

    this.loadHtml(webview)

    const state = new StateStore(this.context)
    this.bridge = new Bridge(
      state,
      (type, data) => {
        if (this.view && !this.disposed) {
          void this.view.webview.postMessage({ type, data })
        }
      },
      // 诊断日志 → "WebApp Chat" 输出通道（不自动弹出，用户可从输出面板选择查看）
      (line) => this.output.appendLine(line),
    )
    console.log('[webapp-chat] bridge installed')

    webviewView.onDidDispose(() => {
      console.log('[webapp-chat] view disposed')
      this.disposed = true
      this.bridge = undefined
      this.view = undefined
    })

    webview.onDidReceiveMessage(async (msg: unknown) => {
      const m = msg as
        | {
            kind?: string
            id?: number
            request?: string
            message?: string
            source?: string
            lineno?: number
          }
        | undefined
      if (!m) return
      if (m.kind === 'reloadWebview') {
        // 兜底页"重新加载"按钮触发：重新读取 webview 产物并覆盖 HTML
        console.log('[webapp-chat] reload webview requested')
        this.loadHtml(webview)
        return
      }
      if (m.kind === 'pageReady') {
        console.log('[webapp-chat] webview page ready (bootstrap executed)')
        return
      }
      if (m.kind === 'pageError') {
        console.error(
          `[webapp-chat] webview page error: ${m.message ?? 'unknown'} @ ${m.source ?? ''}:${m.lineno ?? ''}`,
        )
        return
      }
      if (m.kind !== 'call' || typeof m.request !== 'string' || typeof m.id !== 'number') return
      if (!this.bridge || this.disposed) return
      const reply = await this.bridge.handle(m.request)
      // response 必须是 {"ok":...} JSON 字符串（与 JBCefJSQuery onSuccess 行为一致）
      const response = JSON.stringify(reply)
      if (this.view && !this.disposed) {
        void this.view.webview.postMessage({ __kind: 'reply', id: m.id, response })
      }
    })
  }

  /** 读取并设置 webview HTML；产物缺失/读取失败时展示带"重新加载"的兜底页。 */
  private loadHtml(webview: vscode.Webview): void {
    let html: string
    try {
      const htmlPath = vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'media', 'index.html')
      html = fs.readFileSync(htmlPath.fsPath, 'utf-8')
      console.log(`[webapp-chat] webview html loaded: ${html.length} bytes`)
    } catch (e) {
      console.error('[webapp-chat] webview html 加载失败:', e)
      html = this.fallbackHtml()
    }
    webview.html = html
  }

  /** 产物缺失/加载失败时的兜底页，提供"重新加载"入口。 */
  private fallbackHtml(): string {
    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8"></head>' +
      '<body style="font-family:sans-serif;padding:16px;background:#18191a;color:#d6d6d6">' +
      '<h3 style="margin-top:0">WebApp Chat：webview 加载失败</h3>' +
      '<p>前端产物加载失败或未找到。请确认已执行 <code>npm run build:webview</code>' +
      '（需要前端单文件产物 <code>ai-llmops-web/dist/agent-chat-embed/index.html</code>），' +
      '然后点击下方按钮重新加载。</p>' +
      '<button id="reload" style="padding:6px 14px;border-radius:6px;border:1px solid #3c4043;' +
      'background:#26282b;color:#e8eaed;cursor:pointer">重新加载</button>' +
      '<script>' +
      '(function(){' +
      'try{' +
      'var vscode=acquireVsCodeApi();' +
      "document.getElementById('reload').addEventListener('click',function(){vscode.postMessage({kind:'reloadWebview'})});" +
      '}catch(_){' +
      "document.getElementById('reload').addEventListener('click',function(){window.location.reload()});" +
      '}' +
      '})()' +
      '</script>' +
      '</body></html>'
    )
  }
}
