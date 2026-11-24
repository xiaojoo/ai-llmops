<script setup lang="ts">
import { computed, ref, watch, type PropType } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { useDebugWorkflow } from '@/hooks/use-workflow.ts'
import type { ValidatedError } from '@arco-design/web-vue'

const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  workflow_id: { type: String, required: true, default: '' },
  node_ids: { type: Array as PropType<string[]>, required: false, default: () => [] },
})

const emits = defineEmits([
  'update:visible',
  'node-status',
  'clear-errors',
  'debug-start',
  'debug-end',
])
const { nodes } = useVueFlow()
type DebugNodeResult = {
  node_data: {
    node_type?: string
    type?: string
    title?: string
    id?: string
  }
  node_id?: string
  status?: string
  error?: string
  latency: number
  outputs?: unknown
}
const form = ref<Record<string, unknown>>({})

// 模板表达式不支持 `as X | Y` 联合类型断言（会被解析为过滤器语法），用函数收窄
const asStringValue = (value: unknown): string | undefined => value as string | undefined
const asNumberValue = (value: unknown): number | undefined => value as number | undefined
const asInputValue = (value: unknown): string | number | boolean | undefined =>
  value as string | number | boolean | undefined
const nodeResults = ref<DebugNodeResult[]>([])
const activatedTab = ref('input')
const {
  error: debugWorkflowError,
  loading: debugWorkflowLoading,
  handleDebugWorkflow,
} = useDebugWorkflow()

const inputs = computed(() => {
  const startNode = nodes.value.find((item) => item.type === 'start')
  return startNode?.data?.inputs ?? []
})

const outputs = computed(() => {
  const endNodes = nodeResults.value.filter((item) => item.node_data.node_type === 'end')
  if (endNodes.length === 0) return null
  return endNodes[endNodes.length - 1]?.outputs ?? null
})

const latency = computed(() => {
  return nodeResults.value.reduce((total, item) => total + item.latency, 0)
})

const toolLatency = computed(() => {
  return nodeResults.value.reduce((total, item) => {
    if (item.node_data.type === 'tool') total += item.latency
    return total
  }, 0)
})

// 记录出错节点信息（用于展示面板内的错误定位）
const errorNodeId = ref<string>('')
const errorNodeTitle = ref<string>('')

// 整体运行状态：succeeded / partial_failed / failed / ''
const overallStatus = ref('')

// 失败/跳过节点列表
const failedNodes = ref<{ id: string; title: string; error: string }[]>([])
const skippedNodes = ref<{ id: string; title: string }[]>([])

// 表单字段值更新（:model-value + @update:model-value 绑定）
const setFormValue = (name: string, value: unknown) => {
  form.value[name] = value
}

const onSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  nodeResults.value = []
  debugWorkflowError.value = ''
  errorNodeId.value = ''
  errorNodeTitle.value = ''
  overallStatus.value = ''
  failedNodes.value = []
  skippedNodes.value = []
  if (errors) return

  // 先进入调试模式（屏蔽画布自动保存），再清除节点状态（避免 setEdges 触发 onChange 保存）
  emits('debug-start')
  // 每次运行前通知父组件清除所有节点状态
  emits('clear-errors')

  activatedTab.value = 'output'
  await handleDebugWorkflow(
    props.workflow_id,
    form.value,
    // 节点/汇总事件回调
    (event_response) => {
      const event = event_response.event as string
      const data = event_response.data as Record<string, unknown>
      if (event === 'summary') {
        // 汇总事件：记录整体状态与失败/跳过节点
        overallStatus.value = (data.status as string) ?? ''
        failedNodes.value = []
        skippedNodes.value = []
        for (const fid of (data.failed_node_ids as string[]) ?? []) {
          const r = nodeResults.value.find((item) => item.node_id === fid)
          failedNodes.value.push({
            id: fid,
            title: (r?.node_data?.title as string) ?? fid,
            error: (r?.error as string) ?? '',
          })
        }
        for (const sid of (data.skipped_node_ids as string[]) ?? []) {
          const r = nodeResults.value.find((item) => item.node_id === sid)
          skippedNodes.value.push({
            id: sid,
            title: (r?.node_data?.title as string) ?? sid,
          })
        }
        return
      }
      // 普通节点事件：收集结果 + 通知画布状态
      const nodeResult = data as DebugNodeResult & { node_id?: string; status?: string }
      if (nodeResult.node_id) {
        nodeResults.value.push(nodeResult)
        emits('node-status', { node_id: nodeResult.node_id, status: nodeResult.status ?? 'succeeded' })
      }
    },
    // 错误事件回调（全局失败）
    (error_response) => {
      const data = error_response?.data as
        | { error?: string; error_node_id?: string; error_node_title?: string }
        | undefined
      if (!data) return
      // 将后端返回的 error 信息赋值给 debugWorkflowError 供模板显示
      debugWorkflowError.value = data.error ?? ''
      errorNodeId.value = data.error_node_id ?? ''
      errorNodeTitle.value = data.error_node_title ?? ''
      // 通知父组件（DetailView）将对应节点标红
      if (data.error_node_id) {
        emits('node-status', { node_id: data.error_node_id, status: 'failed' })
      }
    },
    // 节点级调试参数
    props.node_ids && props.node_ids.length > 0 ? { node_ids: props.node_ids } : undefined,
  )
  // 通知父组件调试结束，恢复自动保存
  emits('debug-end')
}

watch(
  () => props.visible,
  (newValue) => {
    if (newValue) {
      debugWorkflowError.value = ''
      nodeResults.value = []
      activatedTab.value = 'input'
      form.value = {}
      errorNodeId.value = ''
      errorNodeTitle.value = ''
      overallStatus.value = ''
      failedNodes.value = []
      skippedNodes.value = []
    }
  },
)

// ── JSON 树渲染 ──────────────────────────────────────────────

/** 折叠状态，key = 节点路径字符串 */
const collapsedPaths = ref<Set<string>>(new Set())

const togglePath = (path: string) => {
  if (collapsedPaths.value.has(path)) {
    collapsedPaths.value.delete(path)
  } else {
    collapsedPaths.value.add(path)
  }
  // 触发响应式更新
  collapsedPaths.value = new Set(collapsedPaths.value)
}

const isCollapsed = (path: string) => collapsedPaths.value.has(path)

/**
 * 把任意 JSON 值递归渲染成带语法色和折叠功能的 VNode 列表
 * 返回 HTML 字符串，通过 v-html 渲染
 */
const renderJson = (value: unknown, path = 'root', indent = 0): string => {
  const pad = '  '.repeat(indent)
  const padInner = '  '.repeat(indent + 1)
  const collapsed = isCollapsed(path)

  if (value === null) return `<span class="json-null">null</span>`
  if (typeof value === 'boolean') return `<span class="json-bool">${value}</span>`
  if (typeof value === 'number') return `<span class="json-num">${value}</span>`
  if (typeof value === 'string') return `<span class="json-str">"${escapeHtml(value)}"</span>`

  if (Array.isArray(value)) {
    if (value.length === 0) return `<span class="json-bracket">[]</span>`
    const preview = `<span class="json-dim">[${value.length} items]</span>`
    if (collapsed) {
      return `<span class="json-toggle" data-path="${path}" onclick="window.__jsonToggle('${path}')">${arrowRight()}${preview}</span>`
    }
    const items = value
      .map(
        (item, i) =>
          `${padInner}${renderJson(item, `${path}[${i}]`, indent + 1)}${i < value.length - 1 ? '<span class="json-dim">,</span>' : ''}`,
      )
      .join('\n')
    return (
      `<span class="json-toggle" data-path="${path}" onclick="window.__jsonToggle('${path}')">${arrowDown()}</span>` +
      `<span class="json-bracket">[</span>\n` +
      `${items}\n` +
      `${pad}<span class="json-bracket">]</span>`
    )
  }

  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const keys = Object.keys(obj)
    if (keys.length === 0) return `<span class="json-bracket">{}</span>`
    const preview = `<span class="json-dim">{${keys.length} keys}</span>`
    if (collapsed) {
      return `<span class="json-toggle" data-path="${path}" onclick="window.__jsonToggle('${path}')">${arrowRight()}${preview}</span>`
    }
    const items = keys
      .map(
        (k, i) =>
          `${padInner}<span class="json-key">"${escapeHtml(k)}"</span><span class="json-colon">: </span>${renderJson(obj[k], `${path}.${k}`, indent + 1)}${i < keys.length - 1 ? '<span class="json-dim">,</span>' : ''}`,
      )
      .join('\n')
    return (
      `<span class="json-toggle" data-path="${path}" onclick="window.__jsonToggle('${path}')">${arrowDown()}</span>` +
      `<span class="json-bracket">{</span>\n` +
      `${items}\n` +
      `${pad}<span class="json-bracket">}</span>`
    )
  }

  return `<span class="json-str">${escapeHtml(String(value))}</span>`
}

const arrowDown = () => `<span class="json-arrow json-arrow--open">▾</span>`
const arrowRight = () => `<span class="json-arrow">▸</span>`

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// 暴露全局 toggle 函数供 onclick 调用
if (typeof window !== 'undefined') {
  ;(window as unknown as { __jsonToggle: (path: string) => void }).__jsonToggle = (path: string) => {
    togglePath(path)
  }
}

/** 最终渲染的 HTML，outputs 或 collapsedPaths 变化时重新计算 */
const jsonHtml = computed(() => {
  if (!outputs.value) return ''
  // 访问 collapsedPaths.value 触发响应式依赖
  void collapsedPaths.value.size
  return renderJson(outputs.value)
})

/** 全部展开 */
const expandAll = () => {
  collapsedPaths.value = new Set()
}
/** 全部折叠（只折叠根） */
const collapseAll = () => {
  collapsedPaths.value = new Set(['root'])
}

/** 复制 JSON */
const copyJson = () => {
  if (!outputs.value) return
  navigator.clipboard.writeText(JSON.stringify(outputs.value, null, 2))
}

// outputs 更新时重置折叠状态
watch(outputs, () => {
  collapsedPaths.value = new Set()
})
</script>

<template>
  <div
    v-if="props.visible"
    class="absolute right-0 top-0 bottom-0 w-[400px] bg-white z-50 border-l overflow-scroll scrollbar-w-none p-4"
  >
    <!-- 调试面板标题 -->
    <div class="flex items-center justify-between mb-2">
      <div class="text-base font-bold text-gray-700">工作流调试</div>
      <a-button
        size="mini"
        type="text"
        class="!text-gray-700"
        @click="() => emits('update:visible', false)"
      >
        <template #icon><icon-close /></template>
      </a-button>
    </div>

    <!-- tab面板 -->
    <a-tabs v-model:active-key="activatedTab">
      <!-- 输入 tab -->
      <a-tab-pane key="input" title="输入">
        <a-empty v-if="inputs.length <= 0" class="my-4">该工作流暂无输入数据</a-empty>
        <a-form :model="form" layout="vertical" @submit="onSubmit">
          <a-form-item
            v-for="(input, idx) in inputs"
            :key="idx"
            :field="input.name"
            :required="input.required"
            hide-asterisk
          >
            <template #label>
              <div class="flex items-center gap-2">
                <div>{{ input.name }}</div>
                <div v-if="input.required" class="text-red-700">*</div>
                <div class="text-xs text-gray-500 bg-gray-200 px-1 py-0.5 rounded shrink-0">
                  {{ input.type }}
                </div>
              </div>
            </template>
            <a-input
              v-if="input.type === 'string'"
              :model-value="asStringValue(form[input.name])"
              @update:model-value="setFormValue(input.name, $event)"
              placeholder="请输入参考值"
              class="!rounded-lg"
            />
            <a-input-number
              v-else-if="['int', 'float'].includes(input.type)"
              :model-value="asNumberValue(form[input.name])"
              @update:model-value="setFormValue(input.name, $event)"
              placeholder="请输入参考值"
              class="!rounded-lg"
            />
            <a-radio-group
              v-else-if="input.type === 'boolean'"
              :model-value="asInputValue(form[input.name])"
              @update:model-value="setFormValue(input.name, $event)"
            >
              <a-radio :value="true">是</a-radio>
              <a-radio :value="false">否</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-button
            :loading="debugWorkflowLoading"
            type="primary"
            html-type="submit"
            long
            class="rounded-lg"
          >
            <template #icon><icon-play-arrow /></template>
            开始运行
          </a-button>
        </a-form>
      </a-tab-pane>

      <!-- 输出 tab -->
      <a-tab-pane key="output" title="输出">
        <!-- 运行中 -->
        <div
          v-if="debugWorkflowLoading"
          class="flex flex-col gap-2 bg-green-100 rounded-lg border border-green-500 p-3 mb-2"
        >
          <div class="flex items-center gap-2">
            <icon-loading class="!text-green-500" />
            <div class="text-green-500">工作流运行中</div>
          </div>
          <div class="text-gray-500 text-xs">
            已成功运行节点【{{ nodeResults.slice(-1)[0]?.node_data?.title ?? '' }}】
          </div>
        </div>

        <!-- 非运行时 -->
        <div v-else class="flex flex-col gap-2">
          <!-- 失败 -->
          <div
            v-if="debugWorkflowError"
            class="flex flex-col gap-2 bg-red-50 p-3 rounded-lg border border-red-400"
          >
            <div class="flex items-center gap-2 text-red-600 font-semibold">
              <icon-exclamation-circle-fill />
              <div>工作流运行失败</div>
            </div>
            <!-- 出错节点定位 -->
            <div v-if="errorNodeTitle" class="flex items-center gap-1.5 text-xs">
              <span class="text-gray-500">出错节点：</span>
              <span
                class="inline-flex items-center gap-1 bg-red-100 border border-red-300 text-red-700 px-2 py-0.5 rounded-md font-medium"
              >
                <icon-close-circle style="font-size: 12px" />
                {{ errorNodeTitle }}
              </span>
            </div>
            <!-- 错误详情 -->
            <div
              class="text-xs text-gray-600 bg-white border border-red-200 rounded-lg p-2 max-h-[160px] overflow-y-auto font-mono whitespace-pre-wrap break-all leading-relaxed"
            >
              {{ debugWorkflowError }}
            </div>
          </div>

          <!-- 部分失败提示 -->
          <div
            v-if="overallStatus === 'partial_failed'"
            class="flex flex-col gap-2 bg-amber-50 p-3 rounded-lg border border-amber-400"
          >
            <div class="flex items-center gap-2 text-amber-600 font-semibold">
              <icon-exclamation-circle-fill />
              <div>运行完成（部分分支失败）</div>
            </div>
            <div v-if="failedNodes.length > 0" class="flex flex-wrap gap-1.5">
              <span
                v-for="f in failedNodes"
                :key="f.id"
                class="inline-flex items-center gap-1 bg-red-100 border border-red-300 text-red-700 px-2 py-0.5 rounded-md text-xs"
              >
                <icon-close-circle style="font-size: 12px" />
                {{ f.title }}
              </span>
            </div>
          </div>

          <!-- 跳过节点列表 -->
          <div v-if="skippedNodes.length > 0" class="flex flex-wrap gap-1.5 text-xs">
            <span
              v-for="s in skippedNodes"
              :key="s.id"
              class="inline-flex items-center gap-1 bg-gray-100 border border-gray-300 text-gray-500 px-2 py-0.5 rounded-md"
            >
              已跳过：{{ s.title }}
            </span>
          </div>

          <!-- 成功统计（仅整体成功时展示；部分失败显示上方琥珀色横幅） -->
          <div
            v-if="outputs && overallStatus === 'succeeded'"
            class="flex flex-col gap-2 bg-green-100 p-3 rounded-lg border border-green-500"
          >
            <div class="flex items-center gap-2 text-green-500">
              <icon-check-circle-fill />
              <div>运行成功</div>
            </div>
            <div class="flex items-center gap-2 text-xs">
              <div class="flex-1 flex flex-col gap-2">
                <div class="text-gray-500">总消耗</div>
                <div class="text-gray-700">500 Tokens</div>
              </div>
              <div class="flex-1 flex flex-col gap-2">
                <div class="text-gray-500">总用时</div>
                <div class="text-gray-700">{{ latency.toFixed(2) }}s</div>
              </div>
              <div class="flex-1 flex flex-col gap-2">
                <div class="text-gray-500">插件消耗</div>
                <div class="text-gray-700">{{ toolLatency.toFixed(2) }}</div>
              </div>
            </div>
          </div>

          <!-- ── JSON 运行结果（整体成功/部分失败且有内容时展示）── -->
          <div
            v-if="
              outputs &&
              Object.keys(outputs).length > 0 &&
              (overallStatus === 'succeeded' || overallStatus === 'partial_failed')
            "
            class="json-viewer"
          >
            <!-- 工具栏 -->
            <div class="json-viewer__toolbar">
              <span class="json-viewer__label">运行结果</span>
              <div class="json-viewer__actions">
                <button class="json-viewer__btn" @click="expandAll" title="全部展开">
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path
                      d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
                    />
                  </svg>
                  展开
                </button>
                <button class="json-viewer__btn" @click="collapseAll" title="全部折叠">
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path
                      d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"
                    />
                  </svg>
                  折叠
                </button>
                <button class="json-viewer__btn" @click="copyJson" title="复制">
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <rect x="9" y="9" width="13" height="13" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  复制
                </button>
              </div>
            </div>
            <!-- 代码区 -->
            <div class="json-viewer__code">
              <pre class="json-pre" v-html="jsonHtml" />
            </div>
          </div>
        </div>

        <!-- 空数据 -->
        <a-empty v-if="!debugWorkflowLoading && !outputs && !debugWorkflowError" class="my-4">
          该工作流暂无运行调试结果
        </a-empty>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<style scoped>
/* ── JSON Viewer 容器 ── */
.json-viewer {
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #2d333b;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
}

/* 工具栏 */
.json-viewer__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  background: #2d333b;
  border-bottom: 1px solid #3d444d;
  user-select: none;
}
.json-viewer__label {
  font-size: 11px;
  color: #768390;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.json-viewer__actions {
  display: flex;
  gap: 4px;
}
.json-viewer__btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 5px;
  border: 1px solid #3d444d;
  background: transparent;
  color: #768390;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.json-viewer__btn:hover {
  background: #3d444d;
  color: #cdd9e5;
  border-color: #539bf5;
}

/* 代码区 */
.json-viewer__code {
  background: #1c2128;
  overflow-x: auto;
  max-height: 480px;
  overflow-y: auto;
  padding: 14px 16px;
}
.json-viewer__code::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
.json-viewer__code::-webkit-scrollbar-track {
  background: #1c2128;
}
.json-viewer__code::-webkit-scrollbar-thumb {
  background: #3d444d;
  border-radius: 4px;
}

/* pre 重置 */
.json-pre {
  margin: 0;
  padding: 0;
  background: transparent;
  white-space: pre;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  color: #cdd9e5;
  tab-size: 2;
}
</style>

<!-- 非 scoped：:deep 无法穿透 v-html，直接全局注入 -->
<style>
/* ── JSON 语法高亮 token ── */
.json-str {
  color: #96d0ff;
}
.json-num {
  color: #f69d50;
}
.json-bool {
  color: #6cb6ff;
}
.json-null {
  color: #768390;
  font-style: italic;
}
.json-key {
  color: #8ddb8c;
}
.json-bracket {
  color: #adbac7;
}
.json-colon {
  color: #adbac7;
}
.json-dim {
  color: #545d68;
  font-style: italic;
}

/* 折叠箭头 */
.json-arrow {
  display: inline-block;
  width: 14px;
  font-size: 10px;
  color: #539bf5;
  cursor: pointer;
  user-select: none;
  transition: color 0.12s;
}
.json-arrow--open {
  color: #539bf5;
}

/* 可点击的折叠区域 */
.json-toggle {
  cursor: pointer;
}
.json-toggle:hover .json-arrow {
  color: #96c7f2;
}
</style>
