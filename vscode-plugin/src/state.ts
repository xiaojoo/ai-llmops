/**
 * 状态持久化（移植自 idea-plugin 的 WebAppSettingsState.java）。
 * - backendUrl / defaultWebAppToken → VS Code 配置（webapp-chat.*）
 * - authToken → SecretStorage（不落明文）
 * - webAppToken / email / lastConversationId → globalState
 */
import * as vscode from 'vscode'

const KEY_WEB_APP_TOKEN = 'webapp.webAppToken'
const KEY_EMAIL = 'webapp.email'
const KEY_LAST_CONVERSATION = 'webapp.lastConversationId'
const SECRET_AUTH_TOKEN = 'webapp.authToken'

export class StateStore {
  private readonly secrets: vscode.SecretStorage
  private readonly global: vscode.Memento

  constructor(private readonly context: vscode.ExtensionContext) {
    this.secrets = context.secrets
    this.global = context.globalState
  }

  // ===== 配置 =====

  backendUrl(): string {
    return (
      vscode.workspace.getConfiguration('webapp-chat').get<string>('backendUrl') || 'http://localhost:5000'
    )
  }

  defaultWebAppToken(): string {
    return (
      vscode.workspace.getConfiguration('webapp-chat').get<string>('defaultWebAppToken') || ''
    )
  }

  // ===== globalState =====

  webAppToken(): string {
    return this.global.get<string>(KEY_WEB_APP_TOKEN) ?? this.defaultWebAppToken()
  }

  async setWebAppToken(token: string): Promise<void> {
    await this.global.update(KEY_WEB_APP_TOKEN, token)
  }

  email(): string {
    return this.global.get<string>(KEY_EMAIL) ?? ''
  }

  async setEmail(email: string): Promise<void> {
    await this.global.update(KEY_EMAIL, email)
  }

  lastConversationId(): string {
    return this.global.get<string>(KEY_LAST_CONVERSATION) ?? ''
  }

  async setLastConversationId(id: string): Promise<void> {
    if (id !== this.lastConversationId()) {
      await this.global.update(KEY_LAST_CONVERSATION, id)
    }
  }

  // ===== SecretStorage（登录 token） =====

  async authToken(): Promise<string> {
    return (await this.secrets.get(SECRET_AUTH_TOKEN)) ?? ''
  }

  async setAuthToken(token: string): Promise<void> {
    if (token) {
      await this.secrets.store(SECRET_AUTH_TOKEN, token)
    } else {
      await this.secrets.delete(SECRET_AUTH_TOKEN)
    }
  }

  async isLoggedIn(): Promise<boolean> {
    return (await this.authToken()) !== ''
  }

  async clearAuth(): Promise<void> {
    await this.secrets.delete(SECRET_AUTH_TOKEN)
  }
}
