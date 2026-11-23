/**
 * Webview 构建脚本：
 * 1. 读取前端单文件产物（ai-llmops-web/dist/agent-chat-embed/index.html）
 * 2. 注入 CSP meta + vscode bridge bootstrap 脚本（在 </head> 前，先于应用脚本执行）
 * 3. 输出到 dist/media/index.html，供 WebviewViewProvider 以 webview.html 加载
 */
const fs = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..')
const WEB_DIST = path.resolve(ROOT, '..', 'ai-llmops-web', 'dist', 'agent-chat-embed', 'index.html')
const OUT_DIR = path.join(ROOT, 'dist', 'media')
const OUT_FILE = path.join(OUT_DIR, 'index.html')

/**
 * vscode bridge：保持与 IDEA 插件 JBCefJSQuery 完全一致的页面侧协议——
 *   JS→宿主：window.agentChatHost({ request, onSuccess, onFailure })
 *     request = JSON.stringify({ action, payload })；onSuccess 收到 {"ok":...} JSON 字符串
 *   宿主→JS：window.__agentChatEvent(JSON.stringify({ type, data }))（由前端 onMounted 注册本体）
 * 宿主回包协议（webview.ts 发送）：
 *   { __kind: 'reply', id, response }               成功（response 为 {"ok":...} JSON 字符串）
 *   { __kind: 'reply', id, errorCode, errorMessage } 协议层失败
 *   { type, data }                                  SSE/状态事件
 */
const BOOTSTRAP = `
<script>
  ;(function () {
    var vscode = acquireVsCodeApi()
    var pending = new Map()
    var seq = 0
    // 诊断：页面脚本执行到 bootstrap 即上报（宿主 console 可确认）
    vscode.postMessage({ kind: 'pageReady' })
    window.addEventListener('error', function (e) {
      try {
        vscode.postMessage({ kind: 'pageError', message: e.message || String(e.error), source: e.filename || '', lineno: e.lineno || 0 })
      } catch (_) {}
    })
    window.addEventListener('unhandledrejection', function (e) {
      try {
        var r = e.reason
        vscode.postMessage({ kind: 'pageError', message: 'Unhandled rejection: ' + ((r && r.message) || String(r)) })
      } catch (_) {}
    })
    window.agentChatHost = function (arg) {
      if (!arg || typeof arg.request !== 'string') return
      var id = ++seq
      pending.set(id, {
        onSuccess: typeof arg.onSuccess === 'function' ? arg.onSuccess : null,
        onFailure: typeof arg.onFailure === 'function' ? arg.onFailure : null,
      })
      vscode.postMessage({ kind: 'call', id: id, request: arg.request })
    }
    window.addEventListener('message', function (e) {
      var msg = e.data
      if (!msg) return
      if (msg.__kind === 'reply') {
        var cb = pending.get(msg.id)
        if (cb) {
          pending.delete(msg.id)
          if (msg.errorCode !== undefined && msg.errorCode !== null) {
            if (cb.onFailure) cb.onFailure(msg.errorCode, msg.errorMessage || '')
          } else if (cb.onSuccess) {
            cb.onSuccess(msg.response)
          }
        }
      } else if (msg && typeof msg.type === 'string') {
        var fn = window.__agentChatEvent
        if (fn) fn(JSON.stringify({ type: msg.type, data: msg.data }))
      }
    })
  })()
</script>
`

const CSP =
  '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; ' +
  "script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  "img-src data: https: http:; font-src data:; connect-src https: http:; " +
  // worker-src/child-src: 放宽 webview 内部 service worker / worker 注册，降低
  // "Could not register service worker" 偶发报错（VS Code webview 已知问题）。
  "worker-src 'self' blob:; child-src 'self' blob:; base-uri 'none';\">"

function build() {
  if (!fs.existsSync(WEB_DIST)) {
    console.error('[build-webview] 缺少前端单文件产物: ' + WEB_DIST)
    console.error('[build-webview] 请先在 ai-llmops-web 执行: npx vite build --config vite.agent-chat.config.ts')
    process.exit(1)
  }
  let html = fs.readFileSync(WEB_DIST, 'utf-8')
  if (!/<meta http-equiv="Content-Security-Policy"/i.test(html)) {
    html = html.replace('<head>', '<head>\n    ' + CSP)
  }
  // 注入标记用 acquireVsCodeApi（应用打包产物里不会出现；window.agentChatHost 会被 app 自身引用，不能当标记）
  if (html.indexOf('acquireVsCodeApi') === -1) {
    html = html.replace('</head>', BOOTSTRAP + '\n  </head>')
  }
  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.writeFileSync(OUT_FILE, html, 'utf-8')
  console.log('[build-webview] 产物: ' + OUT_FILE + ' (' + Buffer.byteLength(html) + ' bytes)')
}

build()
