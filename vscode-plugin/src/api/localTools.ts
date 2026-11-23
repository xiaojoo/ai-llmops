/**
 * Local Tool Runtime —— 插件对用户真实本地工作区执行文件工具。
 *
 * 背景（Remote Agent + Local Tool Runtime）：服务器 Agent 只在插件进程里执行
 * fs_list / fs_read / fs_search，插件是唯一持有绝对路径、唯一做包含性校验的权威。
 *
 * 约定：
 * - 工具名与服务器 workspace_tools 一致（fs_list/fs_stat/fs_read/fs_write/fs_edit/
 *   fs_mkdir/fs_copy/fs_move/fs_delete/fs_search）
 * - 入参为"相对工作区根"路径；返回 JSON 字符串，结构与服务器 fs_* 响应一致
 *   （成功 {"success":true,"operation":..., ...} / 失败 {"success":false,"error":{"code","message"}}）
 * - PathGuard：拒绝绝对路径 / 盘符 / UNC / .. 逃逸 / 符号链接逃逸
 *
 * 写入/删除语义对齐服务器 FileService：
 * - fs_write/fs_edit/fs_mkdir 写入前做编码/大小校验，父目录自动创建
 * - fs_move/fs_delete 对符号链接"操作链接本身"（follow_final=False，等价 mv/rm 不跟随）
 * - fs_delete 一律先进回收站 .agent-trash/<时间戳>-<随机>/<原相对路径>，可恢复
 * - 风险控制：禁止删除工作区根目录、禁止删除工具包内部目录（.agent-trash）
 *
 * 纯逻辑（无 vscode 依赖），可单测。服务器只发相对路径，绝对路径一律本地拒绝。
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

// ===== 返回结构（与服务器 models/responses.py 对齐） =====

interface FsError {
  code: string
  message: string
}

export interface FsResult<T = Record<string, unknown>> {
  success: boolean
  operation: string
  error?: FsError
  [key: string]: unknown
}

type FsToolName =
  | 'fs_list' | 'fs_stat' | 'fs_read' | 'fs_write' | 'fs_edit'
  | 'fs_mkdir' | 'fs_copy' | 'fs_move' | 'fs_delete' | 'fs_search'

// ===== 常量（与服务器策略一致） =====
const MAX_READ_BYTES = 2 * 1024 * 1024
const MAX_READ_CHARS = 50_000
const MAX_LIST_ENTRIES = 500
const MAX_SEARCH_RESULTS = 200
// 单文件写入/编辑上限（字节），对齐服务器 FileSystemPolicy.max_file_size（默认 2MB）
const MAX_FILE_SIZE = 2 * 1024 * 1024
// 回收站目录名，对齐服务器 FileSystemPolicy.trash_dir_name（.agent-trash）
const TRASH_DIR_NAME = '.agent-trash'

/**
 * 默认排除清单（只读真正的源码，依赖/产物/缓存/IDE/框架元数据一律跳过）。
 * 大小写不敏感匹配目录项或文件名（不含路径分隔符）。覆盖：
 * - VCS / IDE / 编辑器元数据
 * - Python 虚拟环境与缓存（venv/.venv/env/__pycache__/site-packages 等）
 * - Node / 前端依赖与构建产物（node_modules/.next/.nuxt/dist 等）
 * - Java / JVM / Gradle / Maven 构建与依赖目录（target/build/.gradle/.mvn 等）
 */
const SKIP_ENTRIES = new Set([
  // VCS / IDE / 编辑器元数据
  '.git', '.svn', '.hg', '.idea', '.vscode', '.vs',
  // Python
  'venv', '.venv', 'env', 'site-packages', '__pycache__', '.tox', '.mypy_cache',
  '.pytest_cache', '.ruff_cache', '.pyre', '.mypy', '.eggs', 'pip-wheel-metadata',
  // Node / 前端
  'node_modules', '.next', '.nuxt', '.parcel-cache', '.turbo', '.pnpm-store',
  'bower_components', 'jspm_packages', 'coverage', '.vite', '.output', '.angular',
  '.svelte-kit', '.cache', '.npm', 'polyfill',
  // Java / JVM / Gradle / Maven
  'target', 'build', 'out', 'classes', '.gradle', '.mvn', '.settings', '.classpath', '.project',
  // 静态/构建产物
  'dist', '.webpack', '.dart_tool', '.pub-cache', '.tmp',
])

/** 生成的二进制/编译产物文件扩展名：fs_read 默认不读（只读真正的代码）。 */
const SKIP_FILE_EXTENSIONS = new Set([
  '.pyc', '.pyo', '.class', '.jar', '.war', '.ear', '.min.js', '.map',
  '.exe', '.dll', '.so', '.dylib', '.o', '.obj', '.a', '.lib',
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svgz',
  '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
  '.woff', '.woff2', '.ttf', '.eot', '.otf', '.mp3', '.mp4', '.wav', '.avi',
  '.db', '.sqlite', '.sqlite3', '.log', '.tiff',
])

/** 判断单个目录项/文件名是否需要排除（大小写不敏感）。 */
function isSkippedName(name: string, skipSet: Set<string>): boolean {
  return skipSet.has(name.toLowerCase())
}

/** 判断文件扩展名是否为生成的二进制/编译产物。 */
function isSkippedFileExtension(name: string, skipExtSet: Set<string>): boolean {
  const ext = path.extname(name).toLowerCase()
  return ext.length > 1 && skipExtSet.has(ext)
}

/**
 * 规范化相对路径为段数组（拒绝绝对路径/盘符/UNC/.. 逃逸）。
 * 返回 null 表示非法；空数组表示工作区根。
 */
function normalizeRelSegments(rel: string): string[] | null {
  if (!rel || !rel.trim()) return []
  if (path.isAbsolute(rel) || /^[a-zA-Z]:[\\/]/.test(rel) || rel.startsWith('\\\\')) return null
  let p = rel.replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '')
  if (!p) return []
  const segs = p.split('/')
  if (segs.includes('..')) return null
  return segs
}

/** 相对路径是否落在被排除的依赖/产物目录内（任一段命中即排除）。 */
function isInsideSkipped(rel: string, skipSet: Set<string>): boolean {
  const segs = normalizeRelSegments(rel)
  if (!segs) return false
  return segs.some((s) => isSkippedName(s, skipSet))
}

// ===== 工作区级排除配置（.webapp/ignore.json） =====

/** 分派给各工具的工作区排除配置（默认=内置清单；用户可经 .webapp/ignore.json 追加）。 */
export interface WorkspaceSkipConfig {
  dirs: Set<string>
  fileExts: Set<string>
}

/** 内置默认排除（基线，只读源码的兜底安全边界）。 */
export function defaultSkipConfig(): WorkspaceSkipConfig {
  return { dirs: new Set(SKIP_ENTRIES), fileExts: new Set(SKIP_FILE_EXTENSIONS) }
}

/**
 * 读取并合并工作区自定义排除配置。
 * 只增不减：用户添加的 dir/ext 是**追加**到内置清单，绝不覆盖/移除内置项，
 * 避免用户误删导致读到依赖包/机密。配置读不到/畸形时回落为纯内置清单。
 * 约定文件：<workspace>/.webapp/ignore.json
 *   { "ignore_dirs": ["target", "*.generated"], "ignore_extensions": [".map", ".tsbuildinfo"] }
 */
export function loadWorkspaceSkipConfig(workspace: string): WorkspaceSkipConfig {
  const cfg = defaultSkipConfig()
  if (!workspace) return cfg
  const ignorePath = path.join(workspace, '.webapp', 'ignore.json')
  let parsed: unknown
  try {
    parsed = JSON.parse(fs.readFileSync(ignorePath, 'utf-8'))
  } catch {
    return cfg // 不存在或不可读：回落内置
  }
  if (!parsed || typeof parsed !== 'object') return cfg
  const obj = parsed as Record<string, unknown>
  for (const d of Array.isArray(obj['ignore_dirs']) ? (obj['ignore_dirs'] as unknown[]) : []) {
    if (typeof d === 'string' && d.trim()) cfg.dirs.add(d.trim().toLowerCase())
  }
  for (const e of Array.isArray(obj['ignore_extensions']) ? (obj['ignore_extensions'] as unknown[]) : []) {
    const ext = typeof e === 'string' ? e.trim().toLowerCase() : ''
    if (ext) cfg.fileExts.add(ext.startsWith('.') ? ext : '.' + ext)
  }
  return cfg
}

function strLen(s: string): number {
  return s.length
}

// ===== PathGuard =====

/**
 * 宽松 realpath：解析到"最深已存在祖先"的真实路径后，再补回尚不存在的末段。
 * 用于写入/创建目标（末段可能不存在）时仍能捕捉"父级符号链接逃逸"——
 * Node 的 realpathSync 对不存在的末段会抛 ENOENT，直接退回词法路径会漏检 symlink 逃逸。
 */
function realpathLenient(p: string): string {
  let cur = path.resolve(p)
  const rest: string[] = []
  const root = path.parse(cur).root
  while (!fs.existsSync(cur) && cur !== root) {
    const parent = path.dirname(cur)
    if (parent === cur) break
    rest.unshift(path.basename(cur))
    cur = parent
  }
  const resolved = fs.realpathSync(cur) // 最深已存在祖先的真实路径（父级符号链接在此被解析）
  return rest.length ? path.join(resolved, ...rest) : resolved
}

/** 把相对工作区根路径解析为绝对路径，并确保仍落在工作区内（拒绝 .. 逃逸/绝对路径/符号链接逃逸）。
 *  followFinal=false（删除/移动）：只解析父目录，最后一段保持原样，保证"操作的是链接本身"、
 *  而不是链接指向的目标（等价服务器 PathGuard.resolve(follow_final=False)）。 */
function resolveSafe(workspace: string, rel: string, followFinal = true): string | null {
  if (!workspace || !rel || !rel.trim()) return null
  if (rel.includes('\0')) return null // 拒绝 NUL（对齐服务器 PathGuard）
  const base = path.resolve(workspace)
  // 绝对路径 / 盘符 / UNC 一律拒绝（服务器只应发相对路径）
  if (path.isAbsolute(rel) || /^[a-zA-Z]:[\\/]/.test(rel) || rel.startsWith('\\\\')) {
    return null
  }
  // 规范化：替换 \ 为 /，去开头 ./ 与 /
  let p = rel.replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '')
  if (p.split('/').includes('..')) return null // 拒绝任何 .. 段
  if (!followFinal) {
    // '.' 整体解析为工作区根：交还调用方判定（删除根会被风险层拦截，返回 RISK_BLOCKED）
    if (p === '.') return path.resolve(base)
    // 不跟随最后一段：分解为父目录（跟随解析）+ 末段原文
    const idx = p.lastIndexOf('/')
    const parentRel = idx >= 0 ? p.slice(0, idx) : ''
    const name = idx >= 0 ? p.slice(idx + 1) : p
    if (!name || name === '..') return null
    const parent = resolveSafe(workspace, parentRel || '.', true)
    if (!parent) return null
    const candidate = path.join(parent, name)
    if (candidate !== base && !candidate.startsWith(base + path.sep)) return null
    return candidate
  }
  const candidate = path.resolve(base, p)
  if (candidate !== base && !candidate.startsWith(base + path.sep)) return null
  try {
    const realBase = fs.realpathSync(base)
    const real = realpathLenient(candidate) // 解析符号链接（父级含 symlink 也能捕捉）
    if (real !== realBase && !real.startsWith(realBase + path.sep)) return null
    return real
  } catch {
    // 路径不存在：仍在工作区内的目标路径返回 candidate（供上层判定 NOT_FOUND）
    return candidate
  }
}

/** 读取文件字节数，超限拒绝。 */
function checkReadable(abs: string): { ok: true; stat: fs.Stats } | { ok: false; error: FsError } {
  if (!fs.existsSync(abs)) {
    return { ok: false, error: err('PATH_NOT_FOUND', `路径不存在：'${abs}'`) }
  }
  const st = fs.statSync(abs)
  if (st.isDirectory()) {
    return { ok: false, error: err('IS_DIRECTORY', '期望文件却得到目录') }
  }
  if (st.size > MAX_READ_BYTES) {
    return { ok: false, error: err('SIZE_LIMIT_EXCEEDED', `文件大小超过单次读取上限 ${MAX_READ_BYTES} 字节`) }
  }
  return { ok: true, stat: st }
}

function err(code: string, message: string): FsError {
  return { code, message }
}

// ===== 辅助（写入/删除/统计共用） =====

/** 构造失败响应（对齐服务器 responses.fail()：operation + error.code/message + 可选 path）。 */
function failRes(operation: string, code: string, message: string, pathVal?: string): FsResult {
  const res: FsResult = { success: false, operation, error: err(code, message) }
  if (pathVal !== undefined) res['path'] = pathVal
  return res
}

/** 字节数 → 可读大小（对齐服务器 _fmt_size）。 */
function fmtSize(sizeBytes: number): string {
  let size = Math.max(0, sizeBytes)
  for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
    if (size < 1024) return `${size.toFixed(1)} ${unit}`
    size /= 1024
  }
  return `${size.toFixed(1)} PB`
}

/** 文件编码 → Node 可识别的 Buffer 编码；不支持返回 null。 */
function normalizeEncoding(encoding: string | undefined): string {
  const e = (encoding || 'utf-8').toLowerCase()
  if (e === 'utf-8' || e === 'utf8') return 'utf8'
  if (e === 'utf-16' || e === 'utf-16le' || e === 'utf16le') return 'utf16le'
  return e
}

/** 把内容按给定编码编码为 Buffer；不支持该编码返回 null。 */
function encodeContent(content: string, encoding: string | undefined): Buffer | null {
  try {
    return Buffer.from(content, normalizeEncoding(encoding) as BufferEncoding)
  } catch {
    return null
  }
}

/** 单条文件/目录信息（fs_stat 使用，对齐服务器 _entry_info，不跟随符号链接）。 */
function entryInfoWorkspace(workspace: string, abs: string, rel: string): Record<string, unknown> {
  const st = fs.lstatSync(abs)
  const isLink = st.isSymbolicLink()
  const isDir = st.isDirectory() && !isLink
  const info: Record<string, unknown> = {
    name: path.basename(abs),
    path: rel,
    type: isLink ? 'symlink' : isDir ? 'directory' : 'file',
    size: st.size,
    size_human: isDir ? '-' : fmtSize(st.size),
    modified: st.mtime.toISOString(),
    created: st.ctime.toISOString(),
    permissions: (st.mode & 0o777).toString(8).padStart(3, '0'),
  }
  if (isLink) {
    try {
      info['target'] = fs.readlinkSync(abs)
    } catch {
      info['target'] = null
    }
  }
  return info
}

/** 用确定性排序的目录复制（覆盖语义：先删目标再复制）。 */
function copyTreeSync(src: string, dst: string): void {
  fs.mkdirSync(dst, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name)
    const d = path.join(dst, entry.name)
    if (entry.isDirectory()) {
      copyTreeSync(s, d)
    } else if (entry.isSymbolicLink()) {
      fs.symlinkSync(fs.readlinkSync(s), d)
    } else {
      fs.copyFileSync(s, d)
    }
  }
}

/** 跨盘/跨设备安全的移动：优先 rename，EXDEV 时退化为复制+删除（等价 shutil.move）。 */
function moveSync(src: string, dst: string): void {
  try {
    fs.renameSync(src, dst)
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code
    if (code === 'EXDEV') {
      fs.mkdirSync(path.dirname(dst), { recursive: true })
      const st = fs.lstatSync(src)
      if (st.isDirectory() && !st.isSymbolicLink()) {
        copyTreeSync(src, dst)
        fs.rmSync(src, { recursive: true, force: true })
      } else {
        fs.copyFileSync(src, dst)
        fs.rmSync(src, { force: true })
      }
      return
    }
    throw e
  }
}

/** 目标是否位于回收站目录内（禁止删除回收站本身/内部）。 */
function isInsideTrashDir(workspace: string, abs: string): boolean {
  const trashRoot = path.join(path.resolve(workspace), TRASH_DIR_NAME)
  const resolved = path.resolve(abs)
  return resolved === trashRoot || resolved.startsWith(trashRoot + path.sep)
}

/** 回收站会话目录：<workspace>/.agent-trash/<UTC时间戳>-<随机6位>。 */
function newTrashSessionDir(workspace: string): string {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
  const rand = Math.random().toString(16).slice(2, 8)
  return path.join(path.resolve(workspace), TRASH_DIR_NAME, `${stamp}-${rand}`)
}

// ===== 工具实现 =====

/** fs_list：列出目录内容（目录在前，文件在后，同类按名称字母序；默认隐藏隐藏项）。 */
export function localFsList(workspace: string, args: { path?: string; show_hidden?: boolean }, skip: WorkspaceSkipConfig = defaultSkipConfig()): FsResult {
  const targetRel = args?.path ?? '.'
  // 只列真正的代码：显式列出被排除的依赖/产物目录时也拒绝
  if (targetRel !== '.' && targetRel !== '' && isInsideSkipped(targetRel, skip.dirs)) {
    return { success: false, operation: 'list', path: targetRel, error: err('SKIPPED', `'${targetRel}' 位于被排除的依赖/产物目录，默认不列出（只读源码）`) }
  }
  const target = resolveSafe(workspace, targetRel)
  if (!target) return { success: false, operation: 'list', error: err('INVALID_PATH', '非法路径（仅允许工作区相对路径）') }
  if (!fs.existsSync(target) || !fs.statSync(target).isDirectory()) {
    return { success: false, operation: 'list', path: targetRel, error: err('NOT_DIRECTORY', `'${targetRel}' 不是一个目录`) }
  }
  let entries = fs.readdirSync(target)
  if (!args?.show_hidden) entries = entries.filter((e) => !e.startsWith('.'))
  // 排除依赖/产物/缓存目录，只列真正的代码（对目标目录本身是否被排除由调用方负责）
  entries = entries.filter((e) => !isSkippedName(e, skip.dirs))
  entries.sort((a, b) => {
    const aIsDir = fs.statSync(path.join(target, a)).isDirectory()
    const bIsDir = fs.statSync(path.join(target, b)).isDirectory()
    if (aIsDir !== bIsDir) return aIsDir ? -1 : 1
    return a.localeCompare(b, undefined, { sensitivity: 'base' })
  })
  const total = entries.length
  const limit = MAX_LIST_ENTRIES
  const truncated = total > limit
  const shown = entries.slice(0, limit)
  const items = shown.map((name) => {
    const abs = path.join(target, name)
    let st: fs.Stats
    try {
      st = fs.lstatSync(abs)
    } catch {
      return { name, path: name, type: 'unknown' }
    }
    const isLink = st.isSymbolicLink()
    const isDir = st.isDirectory() && !isLink
    const rel = toRel(workspace, abs)
    const info: Record<string, unknown> = {
      name,
      path: rel,
      type: isLink ? 'symlink' : isDir ? 'directory' : 'file',
      size: st.size,
    }
    if (isLink) {
      try {
        info['target'] = fs.readlinkSync(abs)
      } catch {
        /* ignore */
      }
    }
    return info
  })
  return {
    success: true,
    operation: 'list',
    path: args?.path || '.',
    total,
    shown: items.length,
    truncated,
    entries: items,
  }
}

/** fs_read：读取文件内容（支持行范围）。 */
export function localFsRead(workspace: string, args: { path: string; start_line?: number; end_line?: number; encoding?: string }, skip: WorkspaceSkipConfig = defaultSkipConfig()): FsResult {
  if (!args?.path) return { success: false, operation: 'read', error: err('INVALID_PATH', 'path 不能为空') }
  // 只读真正的代码：落在被排除的依赖/产物目录内，或为生成产物扩展名，一律拒绝
  if (isInsideSkipped(args.path, skip.dirs)) {
    return { success: false, operation: 'read', path: args.path, error: err('SKIPPED', `'${args.path}' 位于被排除的依赖/产物目录，默认不读取（只读源码）`) }
  }
  const target = resolveSafe(workspace, args.path)
  if (!target) return { success: false, operation: 'read', path: args.path, error: err('INVALID_PATH', '非法路径（仅允许工作区相对路径）') }
  if (isSkippedFileExtension(args.path, skip.fileExts)) {
    return { success: false, operation: 'read', path: args.path, error: err('SKIPPED', `'${args.path}' 为生成/二进制产物，默认不读取（只读源码）`) }
  }
  const chk = checkReadable(target)
  if (!chk.ok) return { success: false, operation: 'read', path: args.path, error: chk.error }
  const encoding = (args?.encoding || 'utf-8') as BufferEncoding
  let all: string
  try {
    all = fs.readFileSync(target, { encoding })
  } catch {
    return { success: false, operation: 'read', path: args.path, error: err('ENCODING_ERROR', `不支持的编码格式：'${encoding}'`) }
  }
  const lines = all.split(/\r?\n/)
  const total = lines.length
  let s = args?.start_line || 1
  let e = args?.end_line ? args.end_line : total
  if (s < 1) s = 1
  if (e > total) e = total
  if (args?.start_line && args.end_line && args.start_line > args.end_line) {
    return { success: false, operation: 'read', path: args.path, error: err('INVALID_ARGUMENT', 'start_line 不能大于 end_line') }
  }
  let content = lines.slice(s - 1, e).join('\n')
  const truncated = strLen(content) > MAX_READ_CHARS
  if (truncated) content = content.slice(0, MAX_READ_CHARS)
  return {
    success: true,
    operation: 'read',
    path: toRel(workspace, target),
    encoding,
    size: chk.stat.size,
    content,
    start_line: s,
    end_line: e,
    total_lines: total,
    char_count: strLen(content),
    truncated,
  }
}

/** fs_search：在工作区内按 glob 模式搜索文件。 */
export function localFsSearch(workspace: string, args: { pattern: string; root?: string; include_hidden?: boolean; limit?: number }, skip: WorkspaceSkipConfig = defaultSkipConfig()): FsResult {
  if (!args?.pattern || !args.pattern.trim()) {
    return { success: false, operation: 'search', error: err('INVALID_ARGUMENT', 'pattern 不能为空') }
  }
  let pattern = args.pattern.replace(/\\/g, '/')
  if (pattern.startsWith('**/')) pattern = pattern.slice(3)
  const matchByPath = pattern.includes('/')
  const rootRel = args?.root ?? '.'
  // 只搜真正的代码：搜索起点位于被排除目录时拒绝
  if (rootRel !== '.' && rootRel !== '' && isInsideSkipped(rootRel, skip.dirs)) {
    return { success: false, operation: 'search', root: rootRel, error: err('SKIPPED', `'${rootRel}' 位于被排除的依赖/产物目录，默认不搜索（只读源码）`) }
  }
  const root = resolveSafe(workspace, rootRel)
  if (!root || !fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    return { success: false, operation: 'search', root: rootRel, error: err('NOT_DIRECTORY', `'${rootRel}' 不是一个目录`) }
  }
  const includeHidden = !!args?.include_hidden
  const limit = Math.min(args?.limit || 100, MAX_SEARCH_RESULTS)
  const matches: { path: string; type: string }[] = []
  let totalFound = 0
  let truncated = false

  function walk(dir: string): void {
    if (truncated) return
    let names: string[]
    try {
      names = fs.readdirSync(dir)
    } catch {
      return
    }
    names = names.filter((n) => {
      if (isSkippedName(n, skip.dirs)) return false
      if (!includeHidden && n.startsWith('.')) return false
      return true
    })
    names.sort((a, b) => a.localeCompare(b))
    for (const name of names) {
      const abs = path.join(dir, name)
      let isDir = false
      try {
        isDir = fs.statSync(abs).isDirectory()
      } catch {
        continue
      }
      const rel = toRel(workspace, abs)
      const matched = matchByPath ? simpleGlob(rel, pattern) : simpleGlob(name, pattern)
      if (matched) {
        totalFound += 1
        const isGeneratedExt = !isDir && isSkippedFileExtension(name, skip.fileExts)
        if (matches.length >= limit || isGeneratedExt) {
          // 生成产物不计入有效结果；达到上限则标记截断
          if (isGeneratedExt) continue
          truncated = true
          return
        }
        matches.push({ path: rel, type: isDir ? 'directory' : 'file' })
      }
      if (isDir) walk(abs)
    }
  }
  walk(root)
  return {
    success: true,
    operation: 'search',
    pattern,
    root: args?.root || '.',
    total_found: totalFound,
    shown: matches.length,
    truncated,
    matches,
  }
}

// ===== 写类工具实现（对齐服务器 FileService 语义） =====

/** 存在的判断（含"断开的符号链接"也算存在，align 服务器 must_exist 的 is_symlink()）。 */
function pathExists(abs: string): boolean {
  try {
    fs.lstatSync(abs)
    return true
  } catch {
    return false
  }
}

/** 递归统计目录下条目数（含子目录内，不含自身；align 服务器 rglob("*")计数）。 */
function countAllEntries(dir: string): number {
  let n = 0
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    n += 1
    if (entry.isDirectory()) n += countAllEntries(path.join(dir, entry.name))
  }
  return n
}

/** 把目标移入回收站（保留相对目录结构），返回回收站内绝对路径；失败返回 null。 */
function trashMove(workspace: string, absPath: string, rawPath: string): string | null {
  try {
    const sessionDir = newTrashSessionDir(workspace)
    fs.mkdirSync(sessionDir, { recursive: true })
    const rel = toRel(workspace, absPath)
    const dest = path.join(sessionDir, rel)
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    moveSync(absPath, dest)
    return dest
  } catch {
    return null
  }
}

/** fs_stat：获取文件/目录信息（不跟随符号链接）。 */
export function localFsStat(workspace: string, args: { path: string }): FsResult {
  if (!args?.path) return failRes('stat', 'INVALID_PATH', 'path 不能为空')
  const target = resolveSafe(workspace, args.path)
  if (!target) return failRes('stat', 'INVALID_PATH', `非法路径（仅允许工作区相对路径）：'${args.path}'`, args.path)
  if (!pathExists(target)) return failRes('stat', 'PATH_NOT_FOUND', `路径不存在：'${args.path}'`, args.path)
  const rel = toRel(workspace, target)
  const { path: _ignored, ...rest } = entryInfoWorkspace(workspace, target, rel)
  return { success: true, operation: 'stat', path: rel, ...rest }
}

/** fs_write：创建/覆盖文件（父目录自动创建；不承担局部修改）。 */
export function localFsWrite(workspace: string, args: { path: string; content: string; encoding?: string }): FsResult {
  if (!args?.path) return failRes('write', 'INVALID_PATH', 'path 不能为空')
  const encoding = args.encoding ?? 'utf-8'
  const content = args.content ?? ''
  const data = encodeContent(content, encoding)
  if (!data) return failRes('write', 'ENCODING_ERROR', `不支持的编码格式：'${encoding}'`, args.path)
  if (data.length > MAX_FILE_SIZE) {
    return failRes('write', 'SIZE_LIMIT_EXCEEDED', `写入内容 ${fmtSize(data.length)} 超过单文件上限 ${fmtSize(MAX_FILE_SIZE)}`, args.path)
  }
  const target = resolveSafe(workspace, args.path)
  if (!target) return failRes('write', 'INVALID_PATH', `非法路径（仅允许工作区相对路径）：'${args.path}'`, args.path)
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
    return failRes('write', 'ALREADY_EXISTS', `'${args.path}' 已存在且是目录`, args.path)
  }
  const created = !fs.existsSync(target)
  try {
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, data)
  } catch (e) {
    return failRes('write', 'OPERATION_FAILED', `写入失败：${(e as Error).message}`, args.path)
  }
  const size = fs.statSync(target).size
  return {
    success: true,
    operation: 'write',
    path: toRel(workspace, target),
    bytes_written: data.length,
    chars_written: content.length,
    created,
    size,
    size_human: fmtSize(size),
  }
}

/** fs_edit：精确替换文件中的文本片段（多处命中仅替换第 1 处）。 */
export function localFsEdit(workspace: string, args: { path: string; old_text: string; new_text: string; encoding?: string }): FsResult {
  if (!args?.path) return failRes('edit', 'INVALID_PATH', 'path 不能为空')
  const encoding = args.encoding ?? 'utf-8'
  const target = resolveSafe(workspace, args.path)
  if (!target) return failRes('edit', 'INVALID_PATH', `非法路径（仅允许工作区相对路径）：'${args.path}'`, args.path)
  if (!pathExists(target)) return failRes('edit', 'PATH_NOT_FOUND', `路径不存在：'${args.path}'`, args.path)
  if (fs.statSync(target).isDirectory()) return failRes('edit', 'IS_DIRECTORY', `'${args.path}' 不是一个文件`, args.path)
  let content: string
  try {
    content = fs.readFileSync(target, { encoding: normalizeEncoding(encoding) as BufferEncoding })
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code
    if (code === 'ERR_UNKNOWN_ENCODING') {
      return failRes('edit', 'ENCODING_ERROR', `不支持的编码格式：'${encoding}'`, args.path)
    }
    return failRes('edit', 'OPERATION_FAILED', `读取文件失败：${(e as Error).message}`, args.path)
  }
  if (!args.old_text) return failRes('edit', 'INVALID_ARGUMENT', 'old_text 不能为空', args.path)
  const occurrences = content.split(args.old_text).length - 1
  if (occurrences === 0) {
    return failRes('edit', 'TARGET_NOT_FOUND', '未找到目标文本（old_text），请先 fs_read 确认当前内容后再编辑', args.path)
  }
  const idx = content.indexOf(args.old_text)
  const changedLine = content.slice(0, idx).split('\n').length
  const newContent = content.replace(args.old_text, args.new_text)
  const data = encodeContent(newContent, encoding)
  if (!data) return failRes('edit', 'ENCODING_ERROR', `新内容无法用 '${encoding}' 编码`, args.path)
  if (data.length > MAX_FILE_SIZE) {
    return failRes('edit', 'SIZE_LIMIT_EXCEEDED', `修改后文件 ${fmtSize(data.length)} 超过单文件上限 ${fmtSize(MAX_FILE_SIZE)}`, args.path)
  }
  try {
    fs.writeFileSync(target, data)
  } catch (e) {
    return failRes('edit', 'OPERATION_FAILED', `写入失败：${(e as Error).message}`, args.path)
  }
  const size = fs.statSync(target).size
  const result: Record<string, unknown> = {
    success: true,
    operation: 'edit',
    path: toRel(workspace, target),
    old_text_chars: args.old_text.length,
    new_text_chars: args.new_text.length,
    replaced_count: 1,
    occurrences,
    changed_line: changedLine,
    bytes_written: data.length,
    size,
    size_human: fmtSize(size),
  }
  if (occurrences > 1) {
    result['warning'] = `目标文本出现 ${occurrences} 次，本次仅替换第 1 处（第 ${changedLine} 行）`
  }
  return result as FsResult
}

/** fs_mkdir：创建目录（mkdir -p 语义，已存在目录幂等成功）。 */
export function localFsMkdir(workspace: string, args: { path: string }): FsResult {
  if (!args?.path) return failRes('mkdir', 'INVALID_PATH', 'path 不能为空')
  const target = resolveSafe(workspace, args.path)
  if (!target) return failRes('mkdir', 'INVALID_PATH', `非法路径（仅允许工作区相对路径）：'${args.path}'`, args.path)
  if (fs.existsSync(target) && fs.statSync(target).isFile()) {
    return failRes('mkdir', 'ALREADY_EXISTS', `'${args.path}' 已存在且是文件，无法创建同名目录`, args.path)
  }
  const existed = fs.existsSync(target) && fs.statSync(target).isDirectory()
  if (!existed) {
    try {
      fs.mkdirSync(target, { recursive: true })
    } catch (e) {
      return failRes('mkdir', 'OPERATION_FAILED', `创建目录失败：${(e as Error).message}`, args.path)
    }
  }
  return { success: true, operation: 'mkdir', path: toRel(workspace, target), created: !existed, existed }
}

/** fs_copy：复制文件或目录（目标存在时需 overwrite=true）。 */
export function localFsCopy(workspace: string, args: { src: string; dst: string; overwrite?: boolean }): FsResult {
  if (!args?.src || !args?.dst) return failRes('copy', 'INVALID_PATH', 'src/dst 不能为空')
  const srcAbs = resolveSafe(workspace, args.src)
  if (!srcAbs) return failRes('copy', 'INVALID_PATH', `非法源路径：'${args.src}'`, args.src)
  if (path.resolve(srcAbs) === path.resolve(workspace)) {
    return failRes('copy', 'RISK_BLOCKED', '禁止复制工作区根目录本身', args.src)
  }
  if (!pathExists(srcAbs)) return failRes('copy', 'PATH_NOT_FOUND', `源路径不存在：'${args.src}'`, args.src)
  const dstAbs = resolveSafe(workspace, args.dst)
  if (!dstAbs) return failRes('copy', 'INVALID_PATH', `非法目标路径：'${args.dst}'`, args.dst)
  if (srcAbs === dstAbs) return failRes('copy', 'INVALID_ARGUMENT', '源路径与目标路径相同', args.src)
  const overwrite = args.overwrite === true
  if (pathExists(dstAbs) && !overwrite) {
    return failRes('copy', 'ALREADY_EXISTS', `目标已存在：'${args.dst}'；如需覆盖请设置 overwrite=true`, args.dst)
  }
  try {
    const st = fs.lstatSync(srcAbs)
    const isLink = st.isSymbolicLink()
    const isDir = st.isDirectory() && !isLink
    fs.mkdirSync(path.dirname(dstAbs), { recursive: true })
    if (isDir) {
      if (pathExists(dstAbs)) fs.rmSync(dstAbs, { recursive: true, force: true })
      copyTreeSync(srcAbs, dstAbs)
      return {
        success: true,
        operation: 'copy',
        src: toRel(workspace, srcAbs),
        dst: toRel(workspace, dstAbs),
        kind: 'directory',
        item_count: countAllEntries(dstAbs),
      }
    }
    if (pathExists(dstAbs)) fs.rmSync(dstAbs, { force: true })
    fs.copyFileSync(srcAbs, dstAbs)
    const size = fs.statSync(dstAbs).size
    return {
      success: true,
      operation: 'copy',
      src: toRel(workspace, srcAbs),
      dst: toRel(workspace, dstAbs),
      kind: 'file',
      bytes_copied: size,
      size_human: fmtSize(size),
    }
  } catch (e) {
    return failRes('copy', 'OPERATION_FAILED', `复制失败：${(e as Error).message}`, args.src)
  }
}

/** fs_move：移动/重命名文件或目录（父目录自动创建；对符号链接移动链接本身）。 */
export function localFsMove(workspace: string, args: { src: string; dst: string }): FsResult {
  if (!args?.src || !args?.dst) return failRes('move', 'INVALID_PATH', 'src/dst 不能为空')
  const srcAbs = resolveSafe(workspace, args.src, false)
  if (!srcAbs) return failRes('move', 'INVALID_PATH', `非法源路径：'${args.src}'`, args.src)
  if (path.resolve(srcAbs) === path.resolve(workspace)) {
    return failRes('move', 'RISK_BLOCKED', '禁止移动工作区根目录本身', args.src)
  }
  if (!pathExists(srcAbs)) return failRes('move', 'PATH_NOT_FOUND', `源路径不存在：'${args.src}'`, args.src)
  const dstAbs = resolveSafe(workspace, args.dst)
  if (!dstAbs) return failRes('move', 'INVALID_PATH', `非法目标路径：'${args.dst}'`, args.dst)
  if (srcAbs === dstAbs) return failRes('move', 'INVALID_ARGUMENT', '源路径与目标路径相同', args.src)
  if (pathExists(dstAbs)) return failRes('move', 'ALREADY_EXISTS', `目标已存在：'${args.dst}'`, args.dst)
  try {
    fs.mkdirSync(path.dirname(dstAbs), { recursive: true })
    moveSync(srcAbs, dstAbs)
  } catch (e) {
    return failRes('move', 'OPERATION_FAILED', `移动失败：${(e as Error).message}`, args.src)
  }
  return { success: true, operation: 'move', src: toRel(workspace, srcAbs), dst: toRel(workspace, dstAbs) }
}

/** fs_delete：删除文件/目录（一律进回收站 .agent-trash，可恢复；非空目录需 recursive=true）。 */
export function localFsDelete(workspace: string, args: { path: string; recursive?: boolean }): FsResult {
  if (!args?.path) return failRes('delete', 'INVALID_PATH', 'path 不能为空')
  const target = resolveSafe(workspace, args.path, false)
  if (!target) return failRes('delete', 'INVALID_PATH', `非法路径（仅允许工作区相对路径）：'${args.path}'`, args.path)
  if (!pathExists(target)) return failRes('delete', 'PATH_NOT_FOUND', '路径不存在', args.path)
  // 风险控制：禁止删工作区根目录本身；禁止删除回收站内部
  if (path.resolve(target) === path.resolve(workspace)) {
    return failRes('delete', 'RISK_BLOCKED', '禁止删除工作区根目录本身', args.path)
  }
  if (isInsideTrashDir(workspace, target)) {
    return failRes('delete', 'RISK_BLOCKED', '禁止删除回收站等工具包内部目录', args.path)
  }
  // 非空目录必须显式 recursive=true
  if (fs.existsSync(target) && fs.statSync(target).isDirectory() && !fs.lstatSync(target).isSymbolicLink()) {
    let isEmpty = true
    try {
      isEmpty = fs.readdirSync(target).length === 0
    } catch {
      isEmpty = false
    }
    if (!isEmpty && args.recursive !== true) {
      return failRes('delete', 'NOT_EMPTY', '目录非空，无法直接删除；如需递归删除整个目录树请将 recursive 设为 true（删除会进入回收站）', args.path)
    }
  }
  const trashDest = trashMove(workspace, target, args.path)
  if (!trashDest) return failRes('delete', 'OPERATION_FAILED', '移入回收站失败', args.path)
  return {
    success: true,
    operation: 'delete',
    path: toRel(workspace, target),
    trashed: true,
    trash_path: toRel(workspace, trashDest),
    recoverable: true,
    restore_hint: '文件已进入回收站 .agent-trash/，可手工移回原路径恢复（V2 将提供 fs_restore）',
  }
}

// ===== 调度入口 =====

/** 根据工具名调用本地实现；返回与服务器一致的 JSON 字符串。 */
export function executeLocalTool(workspace: string, tool: string, args: Record<string, unknown>): string {
  // 读取并合并 .webapp/ignore.json（只增不减），注入各工具作为排除配置
  const skip = loadWorkspaceSkipConfig(workspace)
  let result: FsResult
  switch (tool) {
    case 'fs_list':
      result = localFsList(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '.',
        show_hidden: args?.['show_hidden'] === true,
      }, skip)
      break
    case 'fs_read':
      result = localFsRead(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
        start_line: typeof args?.['start_line'] === 'number' ? (args['start_line'] as number) : undefined,
        end_line: typeof args?.['end_line'] === 'number' ? (args['end_line'] as number) : undefined,
        encoding: typeof args?.['encoding'] === 'string' ? args['encoding'] : undefined,
      }, skip)
      break
    case 'fs_search':
      result = localFsSearch(workspace, {
        pattern: typeof args?.['pattern'] === 'string' ? args['pattern'] : '',
        root: typeof args?.['root'] === 'string' ? args['root'] : undefined,
        include_hidden: args?.['include_hidden'] === true,
        limit: typeof args?.['limit'] === 'number' ? (args['limit'] as number) : undefined,
      }, skip)
      break
    case 'fs_stat':
      result = localFsStat(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
      })
      break
    case 'fs_write':
      result = localFsWrite(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
        content: typeof args?.['content'] === 'string' ? args['content'] : '',
        encoding: typeof args?.['encoding'] === 'string' ? args['encoding'] : undefined,
      })
      break
    case 'fs_edit':
      result = localFsEdit(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
        old_text: typeof args?.['old_text'] === 'string' ? args['old_text'] : '',
        new_text: typeof args?.['new_text'] === 'string' ? args['new_text'] : '',
        encoding: typeof args?.['encoding'] === 'string' ? args['encoding'] : undefined,
      })
      break
    case 'fs_mkdir':
      result = localFsMkdir(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
      })
      break
    case 'fs_copy':
      result = localFsCopy(workspace, {
        src: typeof args?.['src'] === 'string' ? args['src'] : '',
        dst: typeof args?.['dst'] === 'string' ? args['dst'] : '',
        overwrite: args?.['overwrite'] === true,
      })
      break
    case 'fs_move':
      result = localFsMove(workspace, {
        src: typeof args?.['src'] === 'string' ? args['src'] : '',
        dst: typeof args?.['dst'] === 'string' ? args['dst'] : '',
      })
      break
    case 'fs_delete':
      result = localFsDelete(workspace, {
        path: typeof args?.['path'] === 'string' ? args['path'] : '',
        recursive: args?.['recursive'] === true,
      })
      break
    default:
      result = { success: false, operation: tool, error: { code: 'UNSUPPORTED', message: `本地工具运行时未支持：${tool}` } }
  }
  return JSON.stringify(result)
}

// ===== 工具函数 =====

/** 把绝对路径转为相对工作区根路径（服务器语义）。 */
function toRel(workspace: string, abs: string): string {
  const rel = path.relative(path.resolve(workspace), abs)
  return rel ? rel.replace(/\\/g, '/') : '.'
}

function simpleGlob(name: string, pattern: string): boolean {
  // 简化 glob：把 * 转 .* ，? 转 . 后做整串匹配（不处理 [] / ** 的复杂语义，够用）
  const rx = '^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$'
  return new RegExp(rx).test(name)
}

/** 提供给外部复用的 PathGuard（纯逻辑）。 */
export function resolveSafePath(workspace: string, rel: string): string | null {
  return resolveSafe(workspace, rel)
}
