/**
 * 全局表单无障碍自动修复（runtime accessibility auto-fix）
 *
 * 自动处理 axe / Lighthouse 中常见的两类表单问题：
 *  1. 表单控件既没有 id 也没有 name —— 自动为控件分配唯一 id，并在命中常见登录 /
 *     注册字段时补全 name 与 autocomplete，帮助浏览器正确自动填充；
 *  2. <label> 未与表单控件关联 —— 自动为 <label> 补全 for 指向对应控件的 id。
 *
 * 通过 MutationObserver 监听 DOM 变化，Vue 动态渲染、弹窗、抽屉、下拉层中新出现的
 * 控件同样会被自动修复。已在源码中显式声明 id / name / autocomplete 的控件
 * （如登录页）会被自动跳过。
 */

/** 不需要（也无法）关联标签的 input 类型 */
const NON_LABELABLE_INPUT_TYPES = new Set(['hidden', 'submit', 'button', 'reset', 'image'])

/** 不是文本输入框、不参与自动填充映射的 input 类型 */
const NON_TEXT_INPUT_TYPES = new Set(['checkbox', 'radio', 'file', 'range', 'color'])

/** 需要标签关联的表单控件（labelable elements） */
const FIELD_SELECTOR = [
  'input:not([type="hidden"])',
  'input:not([type="submit"])',
  'input:not([type="button"])',
  'input:not([type="reset"])',
  'input:not([type="image"])',
  'select',
  'textarea',
].join(',')

/**
 * Arco InputTag / InputNumber 的真实输入框：所在 v-show 区块隐藏时尺寸为 0，
 * 但它们是用户实际键入的控件，不能被 0 尺寸启发式当作隐藏辅助控件标记 aria-hidden
 */
const INTERACTIVE_INPUT_SELECTOR = '.arco-input-tag-input, .arco-input-number .arco-input'

interface AutofillRule {
  pattern: RegExp
  autocomplete: string
  name: string
}

/** 常见登录 / 注册字段的自动填充映射，按顺序取第一个匹配 */
const AUTOFILL_RULES: AutofillRule[] = [
  { pattern: /确认密码|再次输入密码|新密码|new\s*password/i, autocomplete: 'new-password', name: 'new-password' },
  { pattern: /api\s*key|apikey|密钥|access\s*token|token/i, autocomplete: 'off', name: 'api-key' },
  { pattern: /密码|口令|password/i, autocomplete: 'current-password', name: 'password' },
  { pattern: /验证码|短信码|动态码|captcha/i, autocomplete: 'one-time-code', name: 'code' },
  { pattern: /邮箱|邮件|电子邮件|email/i, autocomplete: 'email', name: 'email' },
  { pattern: /用户名|账号|登录名|手机号|手机|电话|username/i, autocomplete: 'username', name: 'username' },
  { pattern: /姓名|昵称|名字|name/i, autocomplete: 'name', name: 'name' },
  { pattern: /公司|organization/i, autocomplete: 'organization', name: 'organization' },
  { pattern: /地址|address/i, autocomplete: 'street-address', name: 'address' },
  { pattern: /城市|city/i, autocomplete: 'address-level2', name: 'city' },
  { pattern: /国家|country/i, autocomplete: 'country', name: 'country' },
  { pattern: /生日|出生|bday/i, autocomplete: 'bday', name: 'bday' },
  { pattern: /邮编|postal/i, autocomplete: 'postal-code', name: 'postal-code' },
  { pattern: /网址|链接|网站|url|website/i, autocomplete: 'url', name: 'url' },
  { pattern: /搜索|search/i, autocomplete: 'search', name: 'search' },
]

let seq = 0

function nextSeq(): number {
  seq += 1
  return seq
}

/** djb2 哈希：把中文标签稳定映射为 ASCII id 片段 */
function hash(text: string): string {
  let h = 5381
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) + h + text.charCodeAt(i)) >>> 0
  }
  return h.toString(36)
}

/** 提取标签文本中的可读英文片段，作为 id 基础 */
function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
}

function idBaseFor(text: string): string {
  const readable = slug(text)
  return readable || `field-${hash(text) || nextSeq()}`
}

function uniqueId(base: string): string {
  const candidate = base || `field-${nextSeq()}`
  if (!document.getElementById(candidate)) {
    return candidate
  }
  return `${candidate}-${nextSeq()}`
}

function labelTextOf(label: HTMLElement): string {
  return (label.textContent || '').replace(/[*＊]/g, '').replace(/[:：]\s*$/, '').trim()
}

function matchAutofill(text: string): AutofillRule | undefined {
  return AUTOFILL_RULES.find((rule) => rule.pattern.test(text))
}

function isTextLike(field: HTMLElement): boolean {
  if (field instanceof HTMLInputElement) {
    return !NON_TEXT_INPUT_TYPES.has(field.type) && !NON_LABELABLE_INPUT_TYPES.has(field.type)
  }
  return false
}

/** 控件是否已有可访问名称来源：被 label 包裹、或被 label[for] 指向、或带 aria-* */
function hasAssociatedLabel(field: HTMLElement): boolean {
  if (field.closest('label')) return true
  const id = field.id
  if (!id) return false
  return Array.from(document.querySelectorAll<HTMLLabelElement>('label')).some(
    (label) => label.htmlFor === id,
  )
}

/** label 对应的表单控件：优先取所属 form-item 内的控件，其次取父容器内的控件 */
function findAssociableControl(label: HTMLElement): HTMLElement | null {
  const container = label.closest('.arco-form-item') ?? label.parentElement
  return container?.querySelector<HTMLElement>(FIELD_SELECTOR) ?? null
}

function ensureControlId(field: HTMLElement, label: HTMLLabelElement | null): string {
  if (field.id) return field.id

  const labelEl = label ?? field.closest('label')
  const text = labelEl
    ? labelTextOf(labelEl)
    : field.getAttribute('aria-label') || field.getAttribute('placeholder') || ''
  const rule = text ? matchAutofill(text) : undefined
  const base = rule && isTextLike(field) ? rule.name : idBaseFor(text)
  const id = uniqueId(base)
  field.id = id

  // 文本类输入框：补全 name 与 autocomplete，帮助浏览器自动填充
  if (rule && isTextLike(field)) {
    if (!field.hasAttribute('name')) {
      field.setAttribute('name', rule.name)
    }
    if (rule.autocomplete && !field.hasAttribute('autocomplete')) {
      field.setAttribute('autocomplete', rule.autocomplete)
    }
  }

  // 没有任何关联标签的控件：用占位文本补一个可访问名称
  if (!labelEl && !field.getAttribute('aria-label') && !field.getAttribute('aria-labelledby')) {
    const name = text || (rule ? rule.name : '')
    if (name) {
      field.setAttribute('aria-label', name)
    }
  }
  return id
}

/** 执行一轮修复：label 关联 + 控件补 id / name / aria-label */
export function fixA11y(root: ParentNode = document): void {
// ) 为未关联的 <label> 补全 for
  root.querySelectorAll('label').forEach((labelNode) => {
    const label = labelNode as HTMLLabelElement
    if (label.htmlFor) return
    // 已包裹控件的 label（如 a-checkbox / a-radio 内部）属于隐式关联，无需处理
    if (label.querySelector(FIELD_SELECTOR)) return
    const control = findAssociableControl(label)
    if (control) {
      label.htmlFor = ensureControlId(control, label)
    }
  })

// ) 保证每个表单控件都有 id（或 name）以及可访问名称
  root.querySelectorAll<HTMLElement>(FIELD_SELECTOR).forEach((field) => {
    if (!field.id && !field.hasAttribute('name')) {
      ensureControlId(field, null)
    }
    if (
      !hasAssociatedLabel(field) &&
      !field.getAttribute('aria-label') &&
      !field.getAttribute('aria-labelledby') &&
      !field.getAttribute('title')
    ) {
      const placeholder = field.getAttribute('placeholder')
      if (placeholder) {
        field.setAttribute('aria-label', placeholder)
      }
    }
    // 隐藏的辅助控件（如 Arco Select 内部承载值的隐藏输入框）：无任何尺寸且没有任何
    // 可访问名称时，将其移出无障碍树并移出 Tab 顺序（这类控件只是给组件传递值的
    // 纯展示性节点，可见文本由外层的 select 组件本身提供）。
    // 标记是自愈的——控件恢复尺寸或可访问名称（如 v-show 重新显示、占位文本恢复）
    // 后立即清除，避免残留 aria-hidden/tabindex=-1 在控件重新可见并聚焦时触发
    // 浏览器 "Blocked aria-hidden on focused element" 告警
    if (!field.matches(INTERACTIVE_INPUT_SELECTOR)) {
      const rect = field.getBoundingClientRect()
      const isZeroSized = rect.width === 0 || rect.height === 0
      const hasAnyName =
        hasAssociatedLabel(field) ||
        Boolean(
          field.getAttribute('aria-label') ||
            field.getAttribute('aria-labelledby') ||
            field.getAttribute('title') ||
            field.getAttribute('placeholder'),
        )
      if (isZeroSized && !hasAnyName) {
        field.setAttribute('aria-hidden', 'true')
        field.setAttribute('tabindex', '-1')
      } else if (field.getAttribute('aria-hidden') === 'true') {
        field.removeAttribute('aria-hidden')
        if (field.getAttribute('tabindex') === '-1') {
          field.removeAttribute('tabindex')
        }
      }
    }
  })

// ) 消除重复 id：多个 a-form-item 使用相同 field 时，Arco 会为 wrapper 生成相同 id。
  //    保留第一个，其余重新分配唯一 id；被 label[for] / aria-labelledby 引用的不处理
  const seenIds = new Map<string, HTMLElement>()
  root.querySelectorAll<HTMLElement>('[id]').forEach((el) => {
    const id = el.id
    if (!id) return
    if (!seenIds.has(id)) {
      seenIds.set(id, el)
      return
    }
    const referenced = Array.from(root.querySelectorAll('[for], [aria-labelledby]')).some(
      (ref) =>
        ref.getAttribute('for') === id ||
        (ref.getAttribute('aria-labelledby') || '').split(/\s+/).includes(id),
    )
    if (referenced) return
    el.id = uniqueId(id)
  })
}

/**
 * 启用全局表单无障碍自动修复。应在应用挂载后调用一次；
 * 内部通过 MutationObserver 持续修复动态新增的表单控件。
 */
export function setupA11yAutoFix(): void {
  if (typeof document === 'undefined') return
  fixA11y(document)
  const observer = new MutationObserver(() => {
    fixA11y(document)
  })
  observer.observe(document.documentElement, { childList: true, subtree: true })

  // 兜底：任何控件获得焦点时若仍残留 aria-hidden（例如 v-show 重新显示后、
  // 下一次 MutationObserver 触发前就被聚焦），立即清除标记——aria-hidden 与焦点
  // 并存是 WAI-ARIA 明确禁止的，会触发浏览器 "Blocked aria-hidden on focused
  // element" 告警。同时移除随标记写入的 tabindex=-1，让控件恢复可 Tab 聚焦。
  document.addEventListener('focusin', (e) => {
    const target = e.target as HTMLElement
    if (target.hasAttribute('aria-hidden')) {
      target.removeAttribute('aria-hidden')
      if (target.getAttribute('tabindex') === '-1') {
        target.removeAttribute('tabindex')
      }
    }
  })
}
