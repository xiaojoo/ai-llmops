import { test } from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { executeLocalTool, loadWorkspaceSkipConfig, resolveSafePath } from '../src/api/localTools.js'

function makeWs(): string {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'lt-'))
  return base
}

function cleanup(ws: string): void {
  fs.rmSync(ws, { recursive: true, force: true })
}

test('resolveSafePath 拒绝绝对路径/盘符/UNC/.. 逃逸', () => {
  const ws = makeWs()
  try {
    assert.equal(resolveSafePath(ws, 'src/App.vue') !== null, true)
    assert.equal(resolveSafePath(ws, '..\\secret.txt'), null)
    assert.equal(resolveSafePath(ws, '../secret.txt'), null)
    assert.equal(resolveSafePath(ws, 'C:/Users/secret'), null)
    assert.equal(resolveSafePath(ws, '\\\\server\\share\\x'), null)
    assert.equal(resolveSafePath(ws, '/etc/passwd'), null)
  } finally {
    cleanup(ws)
  }
})

test('fs_read 读取工作区内文件内容', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'App.vue'), 'line1\nline2\nline3\n')
    const res = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'src/App.vue' }))
    assert.equal(res.success, true)
    assert.equal(res.operation, 'read')
    // 服务器 Python readlines() 会保留末尾换行——本地实现对齐该语义
    assert.equal(res.content, 'line1\nline2\nline3\n')
  } finally {
    cleanup(ws)
  }
})

test('fs_read 支持行范围', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'a.txt'), '1\n2\n3\n4\n5\n')
    const res = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'src/a.txt', start_line: 2, end_line: 4 }))
    assert.equal(res.success, true)
    assert.equal(res.content, '2\n3\n4')
  } finally {
    cleanup(ws)
  }
})

test('fs_read 越界路径被拒', () => {
  const ws = makeWs()
  try {
    const res = JSON.parse(executeLocalTool(ws, 'fs_read', { path: '../outside.txt' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'INVALID_PATH')
  } finally {
    cleanup(ws)
  }
})

test('fs_list 列出目录且目录在前', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'docs'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'a.txt'), 'x')
    const res = JSON.parse(executeLocalTool(ws, 'fs_list', { path: '.' }))
    assert.equal(res.success, true)
    assert.equal(res.operation, 'list')
    assert.equal(res.entries.length, 3)
    // 目录在前
    assert.equal(res.entries[0].type, 'directory')
  } finally {
    cleanup(ws)
  }
})

test('fs_search 按 pattern 搜索', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'a.py'), 'x')
    fs.writeFileSync(path.join(ws, 'src', 'b.md'), 'x')
    const res = JSON.parse(executeLocalTool(ws, 'fs_search', { pattern: '*.py' }))
    assert.equal(res.success, true)
    assert.equal(res.total_found, 1)
    assert.equal(res.matches[0].path, 'src/a.py')
  } finally {
    cleanup(ws)
  }
})

test('未知工具返回 UNSUPPORTED', () => {
  const ws = makeWs()
  try {
    const res = JSON.parse(executeLocalTool(ws, 'shell_run', { command: 'rm' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'UNSUPPORTED')
  } finally {
    cleanup(ws)
  }
})

test('未选择工作区时工具直接失败（NO_WORKSPACE 由调用方兜底）', () => {
  // executeLocalTool 需要真实 workspace；此用例验证空 workspace 下 fs_read 也能安全失败而不抛异常
  const res = JSON.parse(executeLocalTool('', 'fs_read', { path: 'a.txt' }))
  assert.equal(res.success, false)
})

test('fs_list 排除依赖/产物目录（venv/node_modules/dist）', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'venv'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'node_modules'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'dist'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'a.py'), 'x')
    const res = JSON.parse(executeLocalTool(ws, 'fs_list', { path: '.' }))
    assert.equal(res.success, true)
    const names = res.entries.map((e: { name: string }) => e.name)
    assert.deepEqual(names.sort(), ['a.py', 'src']) // venv/node_modules/dist 被排除
  } finally {
    cleanup(ws)
  }
})

test('fs_list 显式列出被排除目录则拒绝', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'venv'), { recursive: true })
    const res = JSON.parse(executeLocalTool(ws, 'fs_list', { path: 'venv' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'SKIPPED')
  } finally {
    cleanup(ws)
  }
})

test('fs_read 拒绝读取被排除目录内的文件', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'venv', 'lib'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'venv', 'lib', 'x.py'), 'secret')
    const res = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'venv/lib/x.py' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'SKIPPED')
  } finally {
    cleanup(ws)
  }
})

test('fs_read 拒绝生成/二进制产物扩展名', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'app.pyc'), 'bin')
    fs.writeFileSync(path.join(ws, 'logo.png'), 'bin')
    const r1 = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'app.pyc' }))
    assert.equal(r1.success, false)
    assert.equal(r1.error.code, 'SKIPPED')
    const r2 = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'logo.png' }))
    assert.equal(r2.success, false)
    assert.equal(r2.error.code, 'SKIPPED')
  } finally {
    cleanup(ws)
  }
})

test('fs_search 剪枝：不进入依赖目录、不含生成产物', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'node_modules'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'a.py'), 'x')
    fs.writeFileSync(path.join(ws, 'node_modules', 'dep.py'), 'x')
    fs.writeFileSync(path.join(ws, 'src', 'b.pyc'), 'x') // 生成产物
    const res = JSON.parse(executeLocalTool(ws, 'fs_search', { pattern: '*.py' }))
    assert.equal(res.success, true)
    // 只命中 src/a.py，node_modules/dep.py 与 src/b.pyc 被排除
    assert.equal(res.matches.length, 1)
    assert.equal(res.matches[0].path, 'src/a.py')
  } finally {
    cleanup(ws)
  }
})

test('.webapp/ignore.json 追加自定义排除（只增不减）', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, '.webapp'), { recursive: true })
    fs.mkdirSync(path.join(ws, 'custom_dir'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'a.py'), 'x')
    fs.writeFileSync(
      path.join(ws, '.webapp', 'ignore.json'),
      JSON.stringify({ ignore_dirs: ['custom_dir'], ignore_extensions: ['.bundle'] }),
    )
    fs.writeFileSync(path.join(ws, 'b.bundle'), 'x')

    // 自定义目录被排除（fs_list 不列出 custom_dir）
    const list = JSON.parse(executeLocalTool(ws, 'fs_list', { path: '.' }))
    const names = list.entries.map((e: { name: string }) => e.name)
    assert.ok(!names.includes('custom_dir'), '自定义 ignore_dirs 应生效')

    // 自定义扩展名被排除（fs_read 拒绝读 .bundle）
    const read = JSON.parse(executeLocalTool(ws, 'fs_read', { path: 'b.bundle' }))
    assert.equal(read.success, false)
    assert.equal(read.error.code, 'SKIPPED')
  } finally {
    cleanup(ws)
  }
})

test('loadWorkspaceSkipConfig 无配置/畸形配置回落内置', () => {
  // 无 .webapp/ignore.json
  const ws1 = makeWs()
  try {
    const cfg = loadWorkspaceSkipConfig(ws1)
    assert.ok(cfg.dirs.has('node_modules')) // 内置仍在
  } finally {
    cleanup(ws1)
  }
  // 畸形 JSON
  const ws2 = makeWs()
  try {
    fs.mkdirSync(path.join(ws2, '.webapp'), { recursive: true })
    fs.writeFileSync(path.join(ws2, '.webapp', 'ignore.json'), 'not-json{')
    const cfg = loadWorkspaceSkipConfig(ws2)
    assert.ok(cfg.dirs.has('venv')) // 内置仍在
    assert.ok(cfg.fileExts.has('.pyc'))
  } finally {
    cleanup(ws2)
  }
})

// ===== 写类工具（fs_stat/fs_write/fs_edit/fs_mkdir/fs_copy/fs_move/fs_delete） =====

test('fs_write 创建文件并自动创建父目录', () => {
  const ws = makeWs()
  try {
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: 'src/main.py', content: 'print(1)\n' }))
    assert.equal(res.success, true)
    assert.equal(res.operation, 'write')
    assert.equal(res.created, true)
    assert.equal(res.path, 'src/main.py')
    assert.equal(res.bytes_written, 9)
    assert.equal(fs.readFileSync(path.join(ws, 'src', 'main.py'), 'utf-8'), 'print(1)\n')
  } finally {
    cleanup(ws)
  }
})

test('fs_write 覆盖已存在文件（created=false）', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'main.py'), 'old')
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: 'src/main.py', content: 'new' }))
    assert.equal(res.success, true)
    assert.equal(res.created, false)
    assert.equal(fs.readFileSync(path.join(ws, 'src', 'main.py'), 'utf-8'), 'new')
  } finally {
    cleanup(ws)
  }
})

test('fs_write 目标为目录时报 ALREADY_EXISTS', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'd'), { recursive: true })
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: 'd', content: 'x' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'ALREADY_EXISTS')
  } finally {
    cleanup(ws)
  }
})

test('fs_write 越界路径被拒', () => {
  const ws = makeWs()
  try {
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: '../out.txt', content: 'x' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'INVALID_PATH')
  } finally {
    cleanup(ws)
  }
})

test('fs_write 不支持的编码报 ENCODING_ERROR', () => {
  const ws = makeWs()
  try {
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: 'a.txt', content: 'x', encoding: 'gbk' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'ENCODING_ERROR')
  } finally {
    cleanup(ws)
  }
})

test('fs_edit 精确替换第一处并统计', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'x=1\ny=2\nx=1\n')
    const res = JSON.parse(executeLocalTool(ws, 'fs_edit', { path: 'a.txt', old_text: 'x=1', new_text: 'x=9' }))
    assert.equal(res.success, true)
    assert.equal(res.operation, 'edit')
    assert.equal(res.occurrences, 2)
    assert.equal(res.replaced_count, 1)
    assert.equal(res.changed_line, 1)
    assert.equal(res.warning !== undefined, true)
    assert.equal(fs.readFileSync(path.join(ws, 'a.txt'), 'utf-8'), 'x=9\ny=2\nx=1\n')
  } finally {
    cleanup(ws)
  }
})

test('fs_edit 目标文本未找到报 TARGET_NOT_FOUND', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'hello')
    const res = JSON.parse(executeLocalTool(ws, 'fs_edit', { path: 'a.txt', old_text: 'nope', new_text: 'x' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'TARGET_NOT_FOUND')
  } finally {
    cleanup(ws)
  }
})

test('fs_mkdir 创建多级目录且幂等', () => {
  const ws = makeWs()
  try {
    const r1 = JSON.parse(executeLocalTool(ws, 'fs_mkdir', { path: 'a/b/c' }))
    assert.equal(r1.success, true)
    assert.equal(r1.existed, false)
    assert.equal(fs.statSync(path.join(ws, 'a', 'b', 'c')).isDirectory(), true)
    const r2 = JSON.parse(executeLocalTool(ws, 'fs_mkdir', { path: 'a/b/c' }))
    assert.equal(r2.success, true)
    assert.equal(r2.existed, true)
  } finally {
    cleanup(ws)
  }
})

test('fs_copy 复制文件；默认不覆盖、overwrite 生效', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'data')
    const r1 = JSON.parse(executeLocalTool(ws, 'fs_copy', { src: 'a.txt', dst: 'b.txt' }))
    assert.equal(r1.success, true)
    assert.equal(r1.kind, 'file')
    assert.equal(fs.readFileSync(path.join(ws, 'b.txt'), 'utf-8'), 'data')

    const r2 = JSON.parse(executeLocalTool(ws, 'fs_copy', { src: 'a.txt', dst: 'b.txt' }))
    assert.equal(r2.success, false)
    assert.equal(r2.error.code, 'ALREADY_EXISTS')

    const r3 = JSON.parse(executeLocalTool(ws, 'fs_copy', { src: 'a.txt', dst: 'b.txt', overwrite: true }))
    assert.equal(r3.success, true)
  } finally {
    cleanup(ws)
  }
})

test('fs_copy 复制目录', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src', 'sub'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'a.py'), 'x')
    fs.writeFileSync(path.join(ws, 'src', 'sub', 'b.py'), 'y')
    const r = JSON.parse(executeLocalTool(ws, 'fs_copy', { src: 'src', dst: 'dst' }))
    assert.equal(r.success, true)
    assert.equal(r.kind, 'directory')
    assert.equal(fs.existsSync(path.join(ws, 'dst', 'sub', 'b.py')), true)
  } finally {
    cleanup(ws)
  }
})

test('fs_move 移动并自动创建父目录', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'data')
    const r = JSON.parse(executeLocalTool(ws, 'fs_move', { src: 'a.txt', dst: 'x/y/b.txt' }))
    assert.equal(r.success, true)
    assert.equal(r.operation, 'move')
    assert.equal(fs.existsSync(path.join(ws, 'a.txt')), false)
    assert.equal(fs.readFileSync(path.join(ws, 'x', 'y', 'b.txt'), 'utf-8'), 'data')
  } finally {
    cleanup(ws)
  }
})

test('fs_move 目标已存在报 ALREADY_EXISTS', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'data')
    fs.writeFileSync(path.join(ws, 'b.txt'), 'exist')
    const r = JSON.parse(executeLocalTool(ws, 'fs_move', { src: 'a.txt', dst: 'b.txt' }))
    assert.equal(r.success, false)
    assert.equal(r.error.code, 'ALREADY_EXISTS')
  } finally {
    cleanup(ws)
  }
})

test('fs_delete 进回收站（原路径消失、.agent-trash 存在、可恢复）', () => {
  const ws = makeWs()
  try {
    fs.writeFileSync(path.join(ws, 'a.txt'), 'secret')
    const r = JSON.parse(executeLocalTool(ws, 'fs_delete', { path: 'a.txt' }))
    assert.equal(r.success, true)
    assert.equal(r.operation, 'delete')
    assert.equal(r.trashed, true)
    assert.equal(r.recoverable, true)
    assert.equal(fs.existsSync(path.join(ws, 'a.txt')), false)
    assert.equal(fs.existsSync(path.join(ws, '.agent-trash')), true)
    // 回收站内能找到原内容（可恢复）
    assert.ok(fs.readdirSync(path.join(ws, '.agent-trash')).length >= 1)
  } finally {
    cleanup(ws)
  }
})

test('fs_delete 非空目录需 recursive 否则 NOT_EMPTY', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'd'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'd', 'keep.txt'), 'x')
    const r1 = JSON.parse(executeLocalTool(ws, 'fs_delete', { path: 'd' }))
    assert.equal(r1.success, false)
    assert.equal(r1.error.code, 'NOT_EMPTY')

    const r2 = JSON.parse(executeLocalTool(ws, 'fs_delete', { path: 'd', recursive: true }))
    assert.equal(r2.success, true)
    assert.equal(fs.existsSync(path.join(ws, 'd')), false)
  } finally {
    cleanup(ws)
  }
})

test('fs_delete 禁止删工作区根目录', () => {
  const ws = makeWs()
  try {
    const r = JSON.parse(executeLocalTool(ws, 'fs_delete', { path: '.' }))
    assert.equal(r.success, false)
    assert.equal(r.error.code, 'RISK_BLOCKED')
  } finally {
    cleanup(ws)
  }
})

test('fs_delete 越界路径被拒', () => {
  const ws = makeWs()
  try {
    const r = JSON.parse(executeLocalTool(ws, 'fs_delete', { path: '../outside' }))
    assert.equal(r.success, false)
    assert.equal(r.error.code, 'INVALID_PATH')
  } finally {
    cleanup(ws)
  }
})

test('fs_stat 返回文件信息', () => {
  const ws = makeWs()
  try {
    fs.mkdirSync(path.join(ws, 'src'), { recursive: true })
    fs.writeFileSync(path.join(ws, 'src', 'a.py'), 'x')
    const r = JSON.parse(executeLocalTool(ws, 'fs_stat', { path: 'src/a.py' }))
    assert.equal(r.success, true)
    assert.equal(r.operation, 'stat')
    assert.equal(r.path, 'src/a.py')
    assert.equal(r.type, 'file')
    assert.equal(r.size, 1)
    assert.ok(typeof r.modified === 'string')
  } finally {
    cleanup(ws)
  }
})

test('fs_write 拒绝经符号链接的父目录逃逸到工作区外', (t) => {
  const ws = makeWs()
  const outside = makeWs()
  try {
    const linkDir = path.join(ws, 'linkdir')
    try {
      // Windows 目录联接(junction)无需管理员/开发者模式即可创建
      fs.symlinkSync(outside, linkDir, 'junction')
    } catch (e) {
      t.skip('当前环境无法创建符号链接（可能需要 Windows 开发者模式）：' + (e as Error).message)
      return
    }
    const res = JSON.parse(executeLocalTool(ws, 'fs_write', { path: 'linkdir/escape.txt', content: 'x' }))
    assert.equal(res.success, false)
    assert.equal(res.error.code, 'INVALID_PATH')
    assert.equal(fs.existsSync(path.join(outside, 'escape.txt')), false, '不应在工作区外写入文件')
  } finally {
    cleanup(ws)
    cleanup(outside)
  }
})

