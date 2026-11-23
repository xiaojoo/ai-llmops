import { test } from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import {
  parseRequest,
  toChatMessages,
  toChatSessions,
  toWebAppInfo,
  deltaJson,
  askUserJson,
  errorJson,
  resolveProjectPath,
  ok,
  err,
} from '../src/protocol.js'
import type { ParsedEvent } from '../src/api/sse.js'

// ===== parseRequest =====

test('parseRequest 提取 action/payload', () => {
  const r = parseRequest(JSON.stringify({ action: 'login', payload: { email: 'a' } }))
  assert.equal(r.action, 'login')
  assert.deepEqual(r.payload, { email: 'a' })
})

test('parseRequest 畸形 JSON 返回空 action', () => {
  assert.equal(parseRequest('not-json').action, '')
  assert.equal(parseRequest('').action, '')
})

test('parseRequest 缺 payload 容错为空对象', () => {
  const r = parseRequest(JSON.stringify({ action: 'authStatus' }))
  assert.equal(r.action, 'authStatus')
  assert.deepEqual(r.payload, {})
})

// ===== toChatMessages =====

test('toChatMessages 后端倒序行拆成 user+assistant 并正序', () => {
  const rows = [
    { id: '2', query: '问题2', answer: '回答2' },
    { id: '1', query: '问题1', answer: '回答1' },
  ]
  const msgs = toChatMessages(rows, 'c1')
  assert.deepEqual(
    msgs.map((m) => [m.role, m.content]),
    [
      ['user', '问题1'],
      ['assistant', '回答1'],
      ['user', '问题2'],
      ['assistant', '回答2'],
    ],
  )
  assert.equal(msgs[1].messageId, '1')
  assert.equal(msgs[1].conversationId, 'c1')
})

test('toChatMessages 透传 file_urls / latency / total_token_count / feedback', () => {
  const rows = [
    {
      id: '1',
      query: 'q',
      answer: 'a',
      file_urls: [
        { id: 'f1', name: 'a.txt' },
        { name: '' },
      ],
      latency: 3.2,
      total_token_count: 100,
      feedback: 'like',
    },
  ]
  const msgs = toChatMessages(rows, 'c1')
  assert.deepEqual(msgs[0].files, [{ id: 'f1', label: 'a.txt' }])
  assert.equal(msgs[1].latency, 3.2)
  assert.equal(msgs[1].totalTokenCount, 100)
  assert.equal(msgs[1].feedback, 'like')
})

test('toChatMessages 空 query/answer 的行跳过', () => {
  const msgs = toChatMessages([{ id: '1', query: '', answer: '' }], 'c1')
  assert.equal(msgs.length, 0)
})

// ===== toChatSessions =====

test('toChatSessions 映射 id/name/created_at/dialog_round', () => {
  const sessions = toChatSessions([
    { id: 's1', name: '会话', created_at: '2026-01-01', dialog_round: 5 },
  ])
  assert.deepEqual(sessions, [{ id: 's1', title: '会话', time: '2026-01-01', dialogRound: 5 }])
})

// ===== toWebAppInfo =====

test('toWebAppInfo 从 app_config 嵌套读取 dialog_round（后端 GetWebAppResp 结构）', () => {
  const info = toWebAppInfo({ name: 'App', icon: 'i', app_config: { dialog_round: 8 } }, 'tok1')
  assert.deepEqual(info, {
    name: 'App',
    icon: 'i',
    token: 'tok1',
    dialogRound: 8,
    speechToTextEnabled: false,
  })
})

test('toWebAppInfo 顶层 dialog_round 被忽略（应读 app_config 内）', () => {
  const info = toWebAppInfo({ name: 'App', icon: 'i', dialog_round: 3 }, 'tok1')
  assert.equal(info.dialogRound, undefined)
})

// ===== 事件数据构建 =====

function evt(partial: Partial<ParsedEvent>): ParsedEvent {
  return { kind: 'messageDelta', content: '', ...partial }
}

test('deltaJson 只带存在的可选字段', () => {
  assert.deepEqual(deltaJson(evt({ content: 'x' })), { content: 'x' })
  assert.deepEqual(deltaJson(evt({ content: 'x', taskId: 't', conversationId: 'c', messageId: 'm' })), {
    content: 'x',
    taskId: 't',
    conversationId: 'c',
    messageId: 'm',
  })
})

test('askUserJson option 模式：allow_custom 驼峰转换 + 默认值', () => {
  const d = askUserJson(
    evt({
      kind: 'askUser',
      content: '选哪个',
      taskId: 't1',
      raw: { id: 'e1', question: '选哪个', allow_custom: true, options: ['A', 'B'] },
    }),
  )
  assert.deepEqual(d, {
    taskId: 't1',
    eventId: 'e1',
    question: '选哪个',
    allowCustom: true,
    options: ['A', 'B'],
    mode: 'option',
  })
})

test('askUserJson plan 模式：sub_task_options → subTaskOptions + mode=plan', () => {
  const d = askUserJson(
    evt({
      kind: 'askUser',
      taskId: 't1',
      raw: { id: 'e2', question: '执行计划?', allow_custom: false, sub_task_options: [{ order: 1 }] },
    }),
  )
  assert.equal(d.mode, 'plan')
  assert.deepEqual(d.subTaskOptions, [{ order: 1 }])
  assert.equal(d.allowCustom, false)
})

test('askUserJson 缺字段时给默认 eventId/allowCustom', () => {
  const d = askUserJson(evt({ kind: 'askUser', taskId: 't1' }))
  assert.equal(d.eventId, '')
  assert.equal(d.allowCustom, true)
})

test('errorJson 结构', () => {
  assert.deepEqual(errorJson('出错了'), { message: '出错了' })
})

// ===== resolveProjectPath =====

test('resolveProjectPath 只允许工作区内文件', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'webapp-chat-test-'))
  const f = path.join(base, 'a.txt')
  fs.writeFileSync(f, 'x')
  try {
    assert.equal(resolveProjectPath(base, 'a.txt'), f)
    assert.equal(resolveProjectPath(base, '../outside.txt'), null)
    assert.equal(resolveProjectPath(base, 'missing.txt'), null)
    assert.equal(resolveProjectPath(base, ''), null)
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

// ===== ok/err =====

test('ok/err 结构', () => {
  assert.deepEqual(ok({ a: 1 }), { ok: true, data: { a: 1 } })
  assert.deepEqual(err('bad'), { ok: false, error: 'bad' })
})
