import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WebAppApiClient, type ChatEvent } from '../src/api/client.js'

/** 构造 stub fetch：按 URL pathname 前缀匹配返回预设 Response */
function stubFetch(routes: Record<string, () => Response>): typeof fetch {
  return (async (input: string | URL, init?: RequestInit) => {
    const pathname = new URL(String(input)).pathname
    for (const [prefix, make] of Object.entries(routes)) {
      if (pathname.startsWith(prefix)) return make()
    }
    return new Response(JSON.stringify({ code: 404, message: 'no route' }), { status: 404 })
  }) as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function sseResponse(text: string): Response {
  const enc = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(enc.encode(text))
        controller.close()
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )
}

test('login 成功返回 access_token/expire_at', async () => {
  const client = new WebAppApiClient('http://localhost:5000/', stubFetch({
    '/auth/password_login': () => jsonResponse({ code: 0, data: { access_token: 'tok', expire_at: 123 } }),
  }))
  const data = await client.login('a@b.com', 'pw')
  assert.deepEqual(data, { access_token: 'tok', expire_at: 123 })
})

test('login 业务失败透传后端 message', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/auth/password_login': () => jsonResponse({ code: 'fail', message: '密码格式错误' }),
  }))
  const data = await client.login('a@b.com', 'pw')
  assert.deepEqual(data, { message: '密码格式错误' })
})

test('login HTTP 4xx 返回 null', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/auth/password_login': () => jsonResponse({ message: 'unauthorized' }, 401),
  }))
  assert.equal(await client.login('a@b.com', 'pw'), null)
})

test('listWebApps 只保留 published 且有 token 的应用', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/apps': () =>
      jsonResponse({
        data: {
          list: [
            { token: 't1', name: 'A', icon: 'i1', status: 'published' },
            { token: 't2', name: 'B', status: 'draft' },
            { name: 'C', status: 'published' },
          ],
        },
      }),
  }))
  const apps = await client.listWebApps('tok')
  assert.deepEqual(apps, [{ token: 't1', name: 'A', icon: 'i1' }])
})

test('chat SSE 逐事件回调并提取 taskId', async () => {
  const sse =
    'event: agent_message\ndata: {"answer":"你","task_id":"t1","conversation_id":"c1"}\n\n' +
    'event: agent_message\ndata: {"answer":"好","task_id":"t1"}\n\n' +
    'event: agent_end\ndata: {"task_id":"t1"}\n\n'
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () => sseResponse(sse),
  }))
  const events: ChatEvent[] = []
  const taskId = await client.chat('wa', 'tok', 'c1', 'hi', null, 'auto', '', (e) => events.push(e))
  assert.equal(taskId, 't1')
  assert.deepEqual(events.map((e) => e.eventName), ['agent_message', 'agent_message', 'agent_end'])
  assert.equal(JSON.parse(events[0].data).answer, '你')
})

test('chat SSE 无空行结尾的事件也会 flush', async () => {
  const sse = 'event: agent_message\ndata: {"answer":"x"}\n'
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () => sseResponse(sse),
  }))
  const events: ChatEvent[] = []
  await client.chat('wa', 'tok', '', 'hi', null, 'auto', '', (e) => events.push(e))
  assert.equal(events.length, 1)
  assert.equal(JSON.parse(events[0].data).answer, 'x')
})

test('chat SSE 解析 id: 行 → ChatEvent.seqId（对齐服务端 [sse-write] seq）', async () => {
  const sse =
    'id: 7\nevent: agent_message\ndata: {"answer":"a","task_id":"t1"}\n\n' +
    'id: 41\nevent: local_tool_call\ndata: {"tool":"fs_read","task_id":"t1"}\n\n' +
    'id: 42\nevent: agent_end\ndata: {"task_id":"t1"}\n\n'
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () => sseResponse(sse),
  }))
  const events: ChatEvent[] = []
  const taskId = await client.chat('wa', 'tok', '', 'hi', null, 'auto', '', (e) => events.push(e))
  assert.equal(taskId, 't1')
  assert.equal(events.length, 3)
  assert.deepEqual(events.map((e) => e.seqId), [7, 41, 42])
})

/** 首次数据后断流（第二次 pull 时 error）的 SSE 响应，模拟连接被硬断 */
function erroringSseResponse(first: string, err: unknown): Response {
  const enc = new TextEncoder()
  let pulls = 0
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1
      if (pulls === 1) {
        controller.enqueue(enc.encode(first))
      } else {
        controller.error(err)
      }
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

test('chat 断流自动带 Last-Event-ID 重连续传（resume 补发后续事件）', async () => {
  const part1 = 'event: agent_message\ndata: {"answer":"a","task_id":"t1","run_id":"run-1"}\n\n'
  const part2 = 'event: agent_end\ndata: {"task_id":"t1"}\n\n'
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    // resume 路由须排在 chat 路由前：chat 前缀也会匹配 resume 路径，靠插入序命中更精确者
    '/web_apps/wa/chat/run-1/resume': () => sseResponse(part2),
    '/web_apps/wa/chat': () => erroringSseResponse(part1, new TypeError('terminated')),
  }))
  const events: ChatEvent[] = []
  const taskId = await client.chat('wa', 'tok', 'c1', 'hi', null, 'auto', '', (e) => events.push(e))
  assert.equal(taskId, 't1')
  assert.deepEqual(events.map((e) => e.eventName), ['agent_message', 'agent_end'])
  assert.equal(events[1].seqId, 0) // 续传流无 id 行 → seq 0
})

test('chat 断流后无 run_id → 不重连直接抛错', async () => {
  const part1 = 'event: agent_message\ndata: {"answer":"a","task_id":"t1"}\n\n'
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () => erroringSseResponse(part1, new TypeError('terminated')),
  }))
  await assert.rejects(
    client.chat('wa', 'tok', '', 'hi', null, 'auto', '', () => {}),
    (e: unknown) => (e as Error).message === 'terminated',
  )
})

// ===== 本地工具结果回传（submitToolResult）重试语义 =====

test('submitToolResult 5xx 自动重试后成功', async () => {
  let calls = 0
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat/t1/tool-result': () => {
      calls += 1
      return calls === 1 ? jsonResponse({}, 500) : jsonResponse({ code: 0 }, 200)
    },
  }))
  const ok = await client.submitToolResult('wa', 'tok', 't1', 'call_1', '{"success":true}', '')
  assert.equal(ok, true)
  assert.equal(calls, 2)
})

test('submitToolResult 4xx（非 408）立即失败不重试', async () => {
  let calls = 0
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat/t1/tool-result': () => {
      calls += 1
      return jsonResponse({}, 400)
    },
  }))
  const ok = await client.submitToolResult('wa', 'tok', 't1', 'call_1', 'r', '')
  assert.equal(ok, false)
  assert.equal(calls, 1)
})

test('submitToolResult 持续 5xx 重试 3 次仍失败返回 false', async () => {
  let calls = 0
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat/t1/tool-result': () => {
      calls += 1
      return jsonResponse({}, 500)
    },
  }))
  const ok = await client.submitToolResult('wa', 'tok', 't1', 'call_1', 'r', '')
  assert.equal(ok, false)
  assert.equal(calls, 3)
})

test('chat HTTP 4xx 返回 null', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () => jsonResponse({ message: 'bad' }, 400),
  }))
  assert.equal(await client.chat('wa', 'tok', '', 'hi', null, 'auto', '', () => {}), null)
})

test('audioToText 成功路径解析 text[0].transcripts[0].text', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/audio/audio_to_text': () =>
      jsonResponse({ code: 'success', data: { text: [{ transcripts: [{ text: '识别结果' }] }] } }),
  }))
  assert.equal(await client.audioToText('tok', 'key1'), '识别结果')
})

test('audioToText 无识别内容返回空串', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/audio/audio_to_text': () => jsonResponse({ code: 'success', data: { text: [] } }),
  }))
  assert.equal(await client.audioToText('tok', 'key1'), '')
})

test('updateConversationDialogRound 传 null 表示恢复默认', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/conversations/c1/settings': () => jsonResponse({ data: { dialog_round: null } }),
  }))
  const data = await client.updateConversationDialogRound('wa', 'c1', null, 'tok')
  assert.ok(data)
  assert.equal(data['dialog_round'], null)
})

// ===== token 失效 → onAuthFailure（sessionExpired 触发源） =====
// 后端把鉴权失败返回成 HTTP 200 + {code:"unauthorized",message}，插件须据此触发重新登录。

test('getWebApp 识别 token 失效：返回 null 并触发 onAuthFailure', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa': () =>
      jsonResponse({ code: 'unauthorized', message: '授权认证凭证已过期，请重新登录', data: {} }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  const data = await client.getWebApp('wa', 'tok')
  assert.equal(data, null)
  assert.equal(authMsg, '授权认证凭证已过期，请重新登录')
})

test('listWebApps 识别 token 失效：返回空列表并触发 onAuthFailure', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/apps': () => jsonResponse({ code: 'unauthorized', message: '解析token出错，请重新登录', data: {} }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  const list = await client.listWebApps('tok')
  assert.deepEqual(list, [])
  assert.equal(authMsg, '解析token出错，请重新登录')
})

test('bootstrapDefaultApp 识别 token 失效：返回 null 并触发 onAuthFailure', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/plugin/bootstrap': () =>
      jsonResponse({ code: 'unauthorized', message: '授权认证凭证已过期，请重新登录', data: {} }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  const data = await client.bootstrapDefaultApp('tok')
  assert.equal(data, null)
  assert.equal(authMsg, '授权认证凭证已过期，请重新登录')
})

test('chat 返回非 SSE 的 JSON 鉴权错误：返回 null 并触发 onAuthFailure', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () =>
      jsonResponse({ code: 'unauthorized', message: '授权认证凭证已过期，请重新登录', data: {} }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  const taskId = await client.chat('wa', 'tok', '', 'hi', null, 'chat', '', () => {})
  assert.equal(taskId, null)
  assert.equal(authMsg, '授权认证凭证已过期，请重新登录')
})

test('chat 返回非 SSE 的业务错误 → 抛错并透传后端 message（不再静默成"未获取到回复"）', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa/chat': () =>
      jsonResponse({ code: 'not_found', message: '该WebApp不存在或者未发布，请核实后重试', data: {} }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  await assert.rejects(
    client.chat('wa', 'tok', '', 'hi', null, 'chat', '', () => {}),
    (e: unknown) => (e as Error).message === '该WebApp不存在或者未发布，请核实后重试',
  )
  assert.equal(authMsg, '') // 非鉴权业务错误不应触发 onAuthFailure
})

test('非 unauthorized 的正常响应不触发 onAuthFailure', async () => {
  const client = new WebAppApiClient('http://localhost:5000', stubFetch({
    '/web_apps/wa': () => jsonResponse({ code: 'success', data: { name: 'App', icon: 'i', token: 'wa' } }),
  }))
  let authMsg = ''
  client.onAuthFailure = (m) => {
    authMsg = m
  }
  const data = await client.getWebApp('wa', 'tok')
  assert.ok(data)
  assert.equal(authMsg, '')
})
