import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseSseEvent } from '../src/api/sse.js'
import { deltaJson } from '../src/protocol.js'

test('agent_message 取 answer 字段为增量', () => {
  const evt = parseSseEvent('agent_message', JSON.stringify({ answer: '你好', task_id: 't1' }))
  assert.equal(evt.kind, 'messageDelta')
  assert.equal(evt.content, '你好')
  assert.equal(evt.taskId, 't1')
})

test('agent_message 空白 answer 也是有效增量', () => {
  const evt = parseSseEvent('agent_message', JSON.stringify({ answer: '\n\n' }))
  assert.equal(evt.kind, 'messageDelta')
  assert.equal(evt.content, '\n\n')
})

test('agent_message 兼容旧 message 数组结构', () => {
  const evt = parseSseEvent(
    'agent_message',
    JSON.stringify({ message: [{ content: 'a' }, { data: { content: 'b' } }, 'c'] }),
  )
  assert.equal(evt.content, 'abc')
})

test('agent_thought 取 thought / llm_output', () => {
  assert.equal(parseSseEvent('agent_thought', JSON.stringify({ thought: '推理' })).content, '推理')
  assert.equal(parseSseEvent('agent_thought', JSON.stringify({ llm_output: '工具' })).content, '工具')
  assert.equal(parseSseEvent('agent_thought', JSON.stringify({})).content, '')
})

test('agent_end / stop / timeout → end', () => {
  for (const name of ['agent_end', 'stop', 'timeout']) {
    assert.equal(parseSseEvent(name, '{}').kind, 'end')
  }
})

test('error 优先 observation 其次 message', () => {
  assert.equal(parseSseEvent('error', JSON.stringify({ observation: '原因A' })).content, '原因A')
  assert.equal(parseSseEvent('error', JSON.stringify({ message: '原因B' })).content, '原因B')
  assert.equal(parseSseEvent('error', JSON.stringify({})).content, '')
})

test('ask_user 带 question/task_id/conversation_id', () => {
  const evt = parseSseEvent(
    'ask_user',
    JSON.stringify({ question: '继续吗', task_id: 't9', conversation_id: 'c1', message_id: 'm1' }),
  )
  assert.equal(evt.kind, 'askUser')
  assert.equal(evt.content, '继续吗')
  assert.equal(evt.taskId, 't9')
  assert.equal(evt.conversationId, 'c1')
  assert.equal(evt.messageId, 'm1')
})

test('local_tool_call → localToolCall 且保留原始 payload', () => {
  const evt = parseSseEvent(
    'local_tool_call',
    JSON.stringify({
      task_id: 'task-1',
      tool: 'fs_read',
      tool_call_id: 'call_8f91',
      tool_input: { path: 'src/App.vue' },
      conversation_id: 'c1',
      message_id: 'm1',
    }),
  )
  assert.equal(evt.kind, 'localToolCall')
  assert.equal(evt.taskId, 'task-1')
  assert.equal(evt.conversationId, 'c1')
  assert.equal(evt.messageId, 'm1')
  assert.equal(evt.raw?.tool, 'fs_read')
  assert.equal(evt.raw?.tool_call_id, 'call_8f91')
})

test('ping / 未知事件 → ignore', () => {
  assert.equal(parseSseEvent('ping', '').kind, 'ignore')
  assert.equal(parseSseEvent('unknown_event', '{}').kind, 'ignore')
})

test('run_id 从 SSE 事件提取（供"主动停止"用）', () => {
  const evt = parseSseEvent(
    'agent_message',
    JSON.stringify({ answer: 'hi', task_id: 't1', run_id: 'run-9', conversation_id: 'c1' }),
  )
  assert.equal(evt.kind, 'messageDelta')
  assert.equal(evt.taskId, 't1')
  assert.equal(evt.runId, 'run-9')
  // deltaJson 透传 runId 给前端
  const delta = deltaJson(evt)
  assert.equal(delta.runId, 'run-9')
})

test('畸形 data 容错', () => {
  const evt = parseSseEvent('agent_message', 'not-json{')
  assert.equal(evt.kind, 'messageDelta')
  assert.equal(evt.content, '')
  assert.equal(evt.taskId, undefined)
})

test('local_tool_call 畸形 data → kind=localToolCall 且 raw 缺失（bridge 据此 WARN 而非静默丢弃）', () => {
  const evt = parseSseEvent('local_tool_call', 'not-json{')
  assert.equal(evt.kind, 'localToolCall')
  assert.equal(evt.raw, undefined)
  assert.equal(evt.taskId, undefined)
})
