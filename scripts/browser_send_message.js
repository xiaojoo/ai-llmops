#!/usr/bin/env node
/**
 * 可复用浏览器任务脚本：登录 LLMOps → 输入消息 → 点击发送 → 校验结果
 *
 * 解决 browser-use 在中文 URL 粘连、视觉识别不稳定下的问题：
 * 不依赖视觉 LLM，直接操作 DOM（结构化定位输入框/发送按钮），
 * 并通过网络请求 + 输入框状态 + AI 回复渲染三重校验确认发送生效。
 *
 * 用法：
 *   node scripts/browser_send_message.js [--message "创建 美食 APP应用"] [--email xxx] [--password xxx]
 *
 * 环境变量（均可覆盖）：
 *   BASE_URL  默认 http://localhost:5173
 *   EMAIL     必填，或通过 --email 传入
 *   PASSWORD  必填，或通过 --password 传入
 *   MESSAGE   默认 创建 美食 APP应用
 *   HEADLESS  默认 true；设 false 可看到浏览器界面
 *   TIMEOUT_MS 单步等待上限，默认 30000
 *
 * 退出码：0=发送并收到回复；2=登录失败；3=发送未生效；4=回复超时；1=其它错误
 * 输出：JSON（{ok, url, step, detail, reply?}）
 */
'use strict';

// ── playwright 模块多路径探测（兼容不同 nvm/全局安装位置） ──
const CANDIDATES = [
  'playwright',
  'C:/nvm4w/nodejs/node_modules/playwright',
  'D:/Program/nvm/v24.1.0/node_modules/playwright',
  'C:/Program Files/nodejs/node_modules/playwright',
];
let playwright = null;
for (const c of CANDIDATES) {
  try {
    playwright = require(c);
    break;
  } catch (_) { /* try next */ }
}
if (!playwright) {
  console.error(JSON.stringify({ ok: false, step: 'init', detail: '未找到 playwright 模块，请先安装：npm i -g playwright' }));
  process.exit(1);
}

// ── 参数与环境变量 ──
const arg = (name) => {
  const i = process.argv.indexOf('--' + name);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : null;
};
const BASE_URL = (arg('base-url') || process.env.BASE_URL || 'http://localhost:5173').replace(/\/$/, '');
const EMAIL = arg('email') || process.env.EMAIL;
const PASSWORD = arg('password') || process.env.PASSWORD;
const MESSAGE = arg('message') || process.env.MESSAGE || '创建 美食 APP应用';
const HEADLESS = (arg('headless') || process.env.HEADLESS || 'true') !== 'false';
const TIMEOUT_MS = Number(arg('timeout') || process.env.TIMEOUT_MS || 30000);
const REPLY_WAIT_MS = Number(arg('reply-timeout') || process.env.REPLY_TIMEOUT_MS || 45000);

const fail = (code, step, detail) => {
  console.error(JSON.stringify({ ok: false, step, detail, url: undefined }));
  process.exit(code);
};

if (!EMAIL || !PASSWORD) {
  fail(1, 'init', '请通过 --email/--password 或 EMAIL/PASSWORD 提供登录凭据');
}

(async () => {
  const browser = await playwright.chromium.launch({ headless: HEADLESS });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const chatRequests = [];
  page.on('request', (req) => {
    if (req.url().includes('/api/assistant_agent/chat')) chatRequests.push(req.url());
  });

  try {
    // 1. 打开首页（未登录会跳转 /auth/login?redirect=/home）
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
    await page.waitForTimeout(1500);
    const url = page.url();
    const step1 = url.includes('/auth/login') ? 'login' : 'home';

    // 2. 若在登录页则登录
    if (step1 === 'login') {
      await page.fill('#login-email', EMAIL);
      await page.fill('#login-password', PASSWORD);
      await page.click('button:has-text("登录")');
      await page.waitForURL('**/home', { timeout: TIMEOUT_MS }).catch(() => {});
      if (!page.url().includes('/home')) {
        const warn = await page.locator('.arco-message').evaluateAll((els) => els.map((e) => e.innerText)).catch(() => []);
        fail(2, 'login', `登录后未进入 /home（当前 ${page.url()}；提示：${warn.join('|') || '无'}）`);
      }
    }
    console.error(JSON.stringify({ ok: true, step: 'login', detail: `已进入 ${page.url()}` }));

    // 3. 定位输入框并输入消息
    const input = page.locator('#ai');
    await input.waitFor({ state: 'visible', timeout: TIMEOUT_MS });
    await input.click();
    await page.keyboard.type(MESSAGE, { delay: 30 });
    await page.waitForTimeout(400);
    const typed = await input.inputValue();
    if (typed.trim() === '') fail(3, 'input', '输入框内容为空，输入未生效');

    // 4. 定位发送按钮（蓝色 only-icon 圆形按钮，内含 icon-send）
    const sendBtn = page
      .locator('button.arco-btn-only-icon')
      .filter({ has: page.locator('.arco-icon-send') })
      .first();
    if ((await sendBtn.count()) === 0) fail(3, 'locate-send', '未找到发送按钮（icon-send）');
    await sendBtn.click({ force: true });
    console.error(JSON.stringify({ ok: true, step: 'click-send', detail: '已点击发送按钮' }));

    // 5. 校验发送生效：chat 请求发出 + 输入框清空
    let chatSent = false;
    for (let i = 0; i < 20 && !chatSent; i++) {
      await page.waitForTimeout(300);
      chatSent = chatRequests.length > 0;
    }
    const cleared = (await input.inputValue()) === '';
    if (!chatSent) fail(3, 'send', '点击发送后未发出 /api/assistant_agent/chat 请求');
    if (!cleared) fail(3, 'send', '点击发送后输入框未清空');
    console.error(JSON.stringify({ ok: true, step: 'send', detail: `chat 请求已发出（${chatRequests.length} 次），输入框已清空` }));

    // 6. 等待 AI 回复渲染（markdown 回复卡片）
    let reply = '';
    for (let i = 0; i < REPLY_WAIT_MS / 1000; i++) {
      await page.waitForTimeout(1000);
      const cards = await page
        .locator('[class*="markdown-body"]')
        .evaluateAll((els) => els.map((e) => (e.innerText || '').trim()))
        .catch(() => []);
      if (cards.some((t) => t.length > 0)) {
        reply = cards.filter((t) => t.length > 0).slice(-1)[0];
        break;
      }
    }
    if (!reply) fail(4, 'reply', '发送已生效但等待 AI 回复超时');

    console.log(JSON.stringify({ ok: true, step: 'done', url: page.url(), reply: reply.slice(0, 500), detail: '任务完成' }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(JSON.stringify({ ok: false, step: 'error', detail: (e && e.message) || String(e) }));
  process.exit(1);
});
