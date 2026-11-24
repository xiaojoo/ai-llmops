<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed, markRaw, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import moment from 'moment'
// ─── 类型定义 ───────────────────────────────────────────────
import type { Edge, VueFlowStore } from '@vue-flow/core'
import { ConnectionMode, Panel, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Background } from '@vue-flow/background'
import dagre from 'dagre'
import {
  useCancelPublishWorkflow,
  useGetDraftGraph,
  useGetWorkflow,
  usePublishWorkflow,
  useUpdateDraftGraph,
} from '@/hooks/use-workflow.ts'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/minimap/dist/style.css'
import StartNode from './components/nodes/StartNode.vue'
import LlmNode from './components/nodes/LLMNode.vue'
import DatasetRetrievalNode from './components/nodes/DatasetRetrievalNode.vue'
import CodeNode from './components/nodes/CodeNode.vue'
import HttpRequestNode from './components/nodes/HttpRequestNode.vue'
import TemplateTransformNode from './components/nodes/TemplateTransformNode.vue'
import ToolNode from './components/nodes/ToolNode.vue'
import EndNode from './components/nodes/EndNode.vue'
import { Message } from '@arco-design/web-vue'
import { generateRandomString } from '@/utils/helper.ts'
import DebugModal from './components/DebugModal.vue'
import NodeListPanel from './components/NodeListPanel.vue'
import StartNodeInfo from './components/infos/StartNodeInfo.vue'
import CodeNodeInfo from './components/infos/CodeNodeInfo.vue'
import LLMNodeInfo from './components/infos/LLMNodeInfo.vue'
import TemplateTransformInfo from './components/infos/TemplateTransformInfo.vue'
import HttpRequestNodeInfo from './components/infos/HttpRequestNodeInfo.vue'
import DatasetRetrievalNodeInfo from './components/infos/DatasetRetrievalNodeInfo.vue'
import ToolNodeInfo from './components/infos/ToolNodeInfo.vue'
import EndNodeInfo from './components/infos/EndNodeInfo.vue'
import { v4 } from 'uuid'

type NodeType =
  | 'start'
  | 'llm'
  | 'tool'
  | 'dataset_retrieval'
  | 'template_transform'
  | 'http_request'
  | 'code'
  | 'end'

interface NodeValue {
  type: 'generated' | 'literal' | 'ref'
  content: string | number
}

interface NodePort {
  name: string
  type: string
  value: NodeValue
}

interface NodeData {
  title: string
  description: string
  inputs?: NodePort[]
  outputs?: NodePort[]
  prompt?: string
  model_config?: Record<string, unknown>
  tool_type?: string
  provider_id?: string
  tool_id?: string
  params?: Record<string, unknown>
  meta?: Record<string, unknown>
  dataset_ids?: string[]
  retrieval_config?: { retrieval_strategy: string; k: number; score: number }
  template?: string
  url?: string
  method?: string
  code?: string
  [key: string]: unknown
}

interface FlowNode {
  id: string
  type: NodeType
  position: { x: number; y: number }
  data: NodeData
  selected?: boolean
  dimensions?: { width: number; height: number }
  [key: string]: unknown
}

interface FlowEdge {
  id: string
  source: string
  target: string
  source_type?: NodeType
  target_type?: NodeType
  style?: Record<string, unknown>
  animated?: boolean
  [key: string]: unknown
}

interface HistorySnapshot {
  nodes: FlowNode[]
  edges: FlowEdge[]
}
// ────────────────────────────────────────────────────────────
const route = useRoute()
const instance = ref<VueFlowStore | null>(null)
const zoomLevel = ref<number>(1)
const zoomOptions = [
  { label: '200%', value: 2 },
  { label: '100%', value: 1 },
  { label: '75%', value: 0.75 },
  { label: '50%', value: 0.5 },
  { label: '25%', value: 0.25 },
]

const NODE_TYPES = {
  start: markRaw(StartNode),
  llm: markRaw(LlmNode),
  tool: markRaw(ToolNode),
  dataset_retrieval: markRaw(DatasetRetrievalNode),
  template_transform: markRaw(TemplateTransformNode),
  http_request: markRaw(HttpRequestNode),
  code: markRaw(CodeNode),
  end: markRaw(EndNode),
}

const NODE_META_LIST: Array<{
  type: NodeType
  label: string
  desc: string
  colorClass: string
  icon: string
}> = [
  {
    type: 'start',
    label: '开始节点',
    desc: '工作流的起始节点，支持定义输入等信息。',
    colorClass: '!bg-blue-700',
    icon: 'home',
  },
  {
    type: 'llm',
    label: '大语言模型',
    desc: '调用大语言模型，根据提示词生成回复。',
    colorClass: '!bg-sky-500',
    icon: 'language',
  },
  {
    type: 'tool',
    label: '扩展插件',
    desc: '调用插件广场或自定义API插件扩展能力。',
    colorClass: '!bg-orange-500',
    icon: 'tool',
  },
  {
    type: 'dataset_retrieval',
    label: '知识库检索',
    desc: '在选定的知识库中检索相关片段。',
    colorClass: '!bg-violet-500',
    icon: 'storage',
  },
  {
    type: 'template_transform',
    label: '模版转换',
    desc: '对多个字符串变量的格式进行处理。',
    colorClass: '!bg-emerald-400',
    icon: 'branch',
  },
  {
    type: 'http_request',
    label: 'HTTP请求',
    desc: '配置外部API服务，并发起HTTP请求。',
    colorClass: '!bg-rose-500',
    icon: 'link',
  },
  {
    type: 'code',
    label: 'Python代码执行',
    desc: '编写代码处理输入输出变量。',
    colorClass: '!bg-cyan-500',
    icon: 'code',
  },
  {
    type: 'end',
    label: '结束节点',
    desc: '定义工作流最终输出的变量。',
    colorClass: '!bg-red-700',
    icon: 'filter',
  },
]

const NODE_DATA_MAP: Record<NodeType, NodeData> = {
  start: {
    title: '开始节点',
    description: '工作流的起点节点，支持定义工作流的起点输入等信息',
    inputs: [],
  },
  llm: {
    title: '大语言模型',
    description: '调用大语言模型，根据输入参数和提示词生成回复。',
    prompt: '',
    model_config: {},
    inputs: [],
    outputs: [{ name: 'output', type: 'string', value: { type: 'generated', content: '' } }],
  },
  tool: {
    title: '扩展插件',
    description: '调用插件广场或自定义API插件，支持能力扩展和复用',
    tool_type: '',
    provider_id: '',
    tool_id: '',
    params: {},
    inputs: [],
    outputs: [{ name: 'text', type: 'string', value: { type: 'generated', content: '' } }],
    meta: {
      type: 'api_tool',
      provider: { id: '', name: '', label: '', icon: '', description: '' },
      tool: { id: '', name: '', label: '', description: '', params: {} },
    },
  },
  dataset_retrieval: {
    title: '知识库检索',
    description: '根据输入的参数，在选定的知识库中检索相关片段并召回，返回切片列表',
    dataset_ids: [],
    retrieval_config: { retrieval_strategy: 'semantic', k: 4, score: 0 },
    inputs: [{ name: 'query', type: 'string', value: { type: 'literal', content: '' } }],
    outputs: [
      { name: 'combine_documents', type: 'string', value: { type: 'generated', content: '' } },
    ],
    meta: { datasets: [] },
  },
  template_transform: {
    title: '模板转换',
    description: '对多个字符串变量的格式进行处理',
    template: '',
    inputs: [],
    outputs: [{ name: 'output', type: 'string', value: { type: 'generated', content: '' } }],
  },
  http_request: {
    title: 'HTTP请求',
    description: '配置外部API服务，并发起请求。',
    url: '',
    method: 'GET',
    inputs: [],
    outputs: [
      { name: 'status_code', type: 'int', value: { type: 'generated', content: 0 } },
      { name: 'text', type: 'string', value: { type: 'generated', content: '' } },
    ],
  },
  code: {
    title: 'Python代码执行',
    description: '编写代码，处理输入输出变量来生成返回值',
    code: '',
    inputs: [],
    outputs: [],
  },
  end: {
    title: '结束节点',
    description: '工作流的结束节点，支持定义工作流最终输出的变量等信息',
    outputs: [],
  },
}

const selectedNode = ref<FlowNode | null>(null)
const nodeInfoVisible = ref(false)
const isInitializing = ref(true)
const isSaving = ref(false)
// 调试运行中标志：调试时屏蔽 onChange 的自动保存，避免节点 class 变化触发多余请求和提示
const isDebugging = ref(false)

// 调试目标节点 id 列表：空数组 = 调试整个工作流
const debugTargetNodeIds = ref<string[]>([])
const debugModalVisible = ref(false)

// 打开调试面板（可携带目标节点）；同时关闭节点详情面板，避免两者同层叠互相遮挡
const openDebugModal = (node_ids: string[] = []) => {
  nodeInfoVisible.value = false
  debugTargetNodeIds.value = node_ids
  debugModalVisible.value = true
}

// 调试单个节点（右键菜单）
const handleDebugNode = () => {
  if (!contextMenu.value.nodeId) return
  const nodeId = contextMenu.value.nodeId
  closeContextMenu()
  openDebugModal([nodeId])
}

// 调试节点状态映射：id → running / succeeded / failed / skipped，用于画布状态徽标
const nodeStatusMap = ref<Record<string, string>>({})

// 设置某个节点的调试状态（事件载荷为 {node_id, status} 单个对象）
const setNodeStatus = ({ node_id, status }: { node_id: string; status: string }) => {
  nodeStatusMap.value = { ...nodeStatusMap.value, [node_id]: status }
}

// 清除所有节点的调试状态（每次重新运行前调用）
const clearNodeStatuses = () => {
  nodeStatusMap.value = {}
}

// 右键菜单状态
const contextMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  isNodeMenu: false,
  isEdgeMenu: false,
  nodeId: '',
  nodeTitle: '',
})
const contextMenuSelectedText = ref('')
const MENU_WIDTH = 170

// 添加节点面板状态
const addNodePanelVisible = ref(false)
// 左侧节点列表面板（"节点"按钮的另一种展示方式，样式同右侧调试面板）
const nodePanelVisible = ref(false)
// 节点列表展示方式：dropdown=悬浮下拉（原效果），left=固定左侧面板；记忆到localStorage
const NODE_LIST_MODE_KEY = 'workflow_node_list_mode'
const nodeListMode = ref<'dropdown' | 'left'>(
  localStorage.getItem(NODE_LIST_MODE_KEY) === 'left' ? 'left' : 'dropdown',
)

// 切换节点列表展示方式
const switchNodeListMode = (mode: 'dropdown' | 'left') => {
  nodeListMode.value = mode
  localStorage.setItem(NODE_LIST_MODE_KEY, mode)
  if (mode === 'left') {
    nodePanelVisible.value = true
  } else {
    nodePanelVisible.value = false
  }
}
const addNodePanelPos = ref({ x: 0, y: 0 })
const PANEL_WIDTH = 232
const PANEL_HEIGHT = 480
const PANEL_MARGIN = 8
const isPanelDragging = ref(false)
const panelDragOffset = ref({ x: 0, y: 0 })

// 拖拽 Ghost
const ghost = ref<{
  visible: boolean
  x: number
  y: number
  label: string
  colorClass: string
  icon: string
}>({ visible: false, x: 0, y: 0, label: '', colorClass: '', icon: '' })
const draggingNodeType = ref<NodeType | ''>('')
const isDraggingItem = ref(false)
const isNodeContextMenuFired = ref(false)

const {
  onPaneReady,
  onViewportChange,
  onConnect,
  findNode,
  onPaneClick,
  onNodeClick,
  onEdgeClick,
  onEdgeContextMenu,
  onNodeDragStop,
  onNodeContextMenu,
  nodes: allNodes,
  screenToFlowCoordinate,
  removeSelectedNodes,
  fitView,
  updateNode,
  setEdges,
} = useVueFlow()

const { loading: getWorkflowLoading, workflow, loadWorkflow } = useGetWorkflow()
const { nodes, edges, loadDraftGraph } = useGetDraftGraph()
const { loading: publishWorkflowLoading, handlePublishWorkflow } = usePublishWorkflow()
const { handleCancelPublish } = useCancelPublishWorkflow()
const {
  loading: updateDraftGraphLoading,
  handleUpdateDraftGraph,
  convertGraphToReq,
} = useUpdateDraftGraph()

// --- 历史记录（撤销/重做）---
const history = ref<HistorySnapshot[]>([])
const future = ref<HistorySnapshot[]>([])

const saveHistory = () => {
  history.value.push({
    nodes: JSON.parse(JSON.stringify(nodes.value)),
    edges: JSON.parse(JSON.stringify(edges.value)),
  })
  future.value = []
}

const canUndo = computed(() => history.value.length > 0)
const canRedo = computed(() => future.value.length > 0)

const undo = () => {
  if (!canUndo.value) return
  future.value.push({
    nodes: JSON.parse(JSON.stringify(nodes.value)),
    edges: JSON.parse(JSON.stringify(edges.value)),
  })
  const prev = history.value.pop()!
  nodes.value = prev.nodes
  edges.value = prev.edges as unknown as Edge[]
  closeContextMenu()
  saveGraph()
}

const redo = () => {
  if (!canRedo.value) return
  history.value.push({
    nodes: JSON.parse(JSON.stringify(nodes.value)),
    edges: JSON.parse(JSON.stringify(edges.value)),
  })
  const next = future.value.pop()!
  nodes.value = next.nodes
  edges.value = next.edges as unknown as Edge[]
  closeContextMenu()
  saveGraph()
}

// --- 节点调试状态同步：nodeStatusMap 变化时，通过 updateNode/updateEdge 更新 Vue Flow 内部节点与连线 ---
// 注意：不能直接替换 nodes.value/edges.value 数组，Vue Flow 内部 store 不会因此更新，
// 必须使用 useVueFlow().updateNode/updateEdge(id, patch) 才能让渲染重新生效。
watch(
  nodeStatusMap,
  (statusMap) => {
    for (const n of nodes.value) {
      const status = statusMap[n.id]
      let cls = ''
      if (status === 'failed') cls = 'node-status-failed'
      else if (status === 'succeeded') cls = 'node-status-succeeded'
      else if (status === 'skipped') cls = 'node-status-skipped'
      else if (status === 'running') cls = 'node-status-running'
      updateNode(n.id, { class: cls })
    }
// 连线随两端节点状态变色：任一端失败→红；两端成功→绿；否则灰
    // 该版本无 updateEdge(id, patch) 样式 API，通过 setEdges 重建边数组走响应式通道
    const nextEdges: Edge[] = edges.value.map((e): Edge => {
      const srcStatus = statusMap[e.source]
      const tgtStatus = statusMap[e.target]
      let stroke = '#9ca3af'
      if (srcStatus === 'failed' || tgtStatus === 'failed') stroke = '#ef4444'
      else if (srcStatus === 'succeeded' && tgtStatus === 'succeeded') stroke = '#22c55e'
      return { ...e, style: { ...(e.style ?? {}), stroke, strokeWidth: 2 } }
    })
    setEdges(nextEdges)
  },
  { deep: false },
)

// --- 调试面板开关时同步 isDebugging 标志 ---
// 调试面板打开时进入调试模式（屏蔽 onChange），关闭时退出
watch(debugModalVisible, (val) => {
  if (!val) isDebugging.value = false
})

// --- 连线选中状态 ---
const selectedEdgeId = ref<string>('')

// --- 右键菜单位置计算 ---
const updateContextMenuPosition = (clientX: number, clientY: number) => {
  contextMenuSelectedText.value = window.getSelection()?.toString() ?? ''
  const { innerWidth: winW, innerHeight: winH } = window
  const padding = 8
  const estimatedH = contextMenu.value.isNodeMenu ? 340 : contextMenu.value.isEdgeMenu ? 180 : 260
  let x = clientX
  let y = clientY
  if (x + MENU_WIDTH + padding > winW) x = clientX - MENU_WIDTH
  if (y + estimatedH + padding > winH) y = clientY - estimatedH
  contextMenu.value.x = Math.max(padding, x)
  contextMenu.value.y = Math.max(padding, y)
  nextTick(() => {
    const menuEl = document.querySelector('.context-menu') as HTMLElement | null
    if (!menuEl) return
    const menuH = menuEl.offsetHeight
    const menuW = menuEl.offsetWidth
    let rx = clientX
    let ry = clientY
    if (rx + menuW + padding > winW) rx = clientX - menuW
    if (ry + menuH + padding > winH) ry = clientY - menuH
    contextMenu.value.x = Math.max(padding, rx)
    contextMenu.value.y = Math.max(padding, ry)
  })
}

// --- 排列逻辑 ---
const layoutOptions = [
  { label: '向左排列 (LR)', value: 'LR', icon: 'icon-left' },
  { label: '向右排列 (RL)', value: 'RL', icon: 'icon-right' },
  { label: '向上排列 (TB)', value: 'TB', icon: 'icon-up' },
  { label: '向下排列 (BT)', value: 'BT', icon: 'icon-down' },
]

const autoLayout = async (direction = 'LR') => {
  const selectedNodes = (nodes.value as FlowNode[]).filter((n) => n.selected)
  const isPartialLayout = selectedNodes.length > 0
  const targetNodes: FlowNode[] = isPartialLayout ? selectedNodes : (nodes.value as FlowNode[])
  if (targetNodes.length === 0) return

  let originalMinX = Infinity
  let originalMinY = Infinity
  let originalMaxX = -Infinity
  let originalMaxY = -Infinity
  targetNodes.forEach((node) => {
    const w = node.dimensions?.width ?? 220
    const h = node.dimensions?.height ?? 100
    if (node.position.x < originalMinX) originalMinX = node.position.x
    if (node.position.y < originalMinY) originalMinY = node.position.y
    if (node.position.x + w > originalMaxX) originalMaxX = node.position.x + w
    if (node.position.y + h > originalMaxY) originalMaxY = node.position.y + h
  })

  const dagreGraph = new dagre.graphlib.Graph()
  dagreGraph.setDefaultEdgeLabel(() => ({}))
  dagreGraph.setGraph({ rankdir: direction, nodesep: 100, ranksep: 120 })

  const targetIds = new Set(targetNodes.map((n) => n.id))
  targetNodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: node.dimensions?.width || 220,
      height: node.dimensions?.height || 100,
    })
  })
  ;(edges.value as FlowEdge[]).forEach((edge) => {
    if (targetIds.has(edge.source) && targetIds.has(edge.target))
      dagreGraph.setEdge(edge.source, edge.target)
  })

  dagre.layout(dagreGraph)

  let dagreMinX = Infinity
  let dagreMinY = Infinity
  let dagreMaxX = -Infinity
  let dagreMaxY = -Infinity
  targetNodes.forEach((node) => {
    const dn = dagreGraph.node(node.id)
    const w = node.dimensions?.width || 220
    const h = node.dimensions?.height || 100
    const nx = dn.x - w / 2
    const ny = dn.y - h / 2
    if (nx < dagreMinX) dagreMinX = nx
    if (ny < dagreMinY) dagreMinY = ny
    if (nx + w > dagreMaxX) dagreMaxX = nx + w
    if (ny + h > dagreMaxY) dagreMaxY = ny + h
  })

  const offsetX = direction === 'RL' ? originalMaxX - dagreMaxX : originalMinX - dagreMinX
  const offsetY = direction === 'BT' ? originalMaxY - dagreMaxY : originalMinY - dagreMinY

  saveHistory()
  nodes.value = (nodes.value as FlowNode[]).map((node) => {
    if (targetIds.has(node.id)) {
      const dn = dagreGraph.node(node.id)
      const w = node.dimensions?.width || 220
      const h = node.dimensions?.height || 100
      return {
        ...node,
        position: { x: dn.x - w / 2 + offsetX, y: dn.y - h / 2 + offsetY },
      }
    }
    return node
  })

  closeContextMenu()
  await nextTick()

  if (!isPartialLayout) {
    setTimeout(() => fitView({ padding: 0.2 }), 50)
  }

  await saveGraph()
}

const addNode = (node_type: NodeType, clientX?: number, clientY?: number) => {
  if (node_type === 'start' && allNodes.value.some((n) => n.type === 'start')) {
    Message.error('工作流中只允许有一个开始节点')
    return
  }
  if (node_type === 'end' && allNodes.value.some((n) => n.type === 'end')) {
    Message.error('工作流中只允许有一个结束节点')
    return
  }

  let position: { x: number; y: number }
  if (clientX !== undefined && clientY !== undefined) {
    position = screenToFlowCoordinate({ x: clientX, y: clientY })
  } else {
    const node_count = allNodes.value.length
    const total = allNodes.value.reduce(
      (acc, item) => {
        acc.xSum += item.position.x
        acc.ySum += item.position.y
        return acc
      },
      { xSum: 0, ySum: 0 },
    )
    position = {
      x: node_count > 0 ? total.xSum / node_count + 100 : 100,
      y: node_count > 0 ? total.ySum / node_count + 100 : 100,
    }
  }

  saveHistory()
  const node_data = NODE_DATA_MAP[node_type]
  nodes.value.push({
    id: v4(),
    type: node_type,
    position,
    data: { ...node_data, title: `${node_data.title}-${generateRandomString(5)}` },
  })
}

const addNodeFromPanel = (node_type: NodeType) => {
  addNode(node_type)
  addNodePanelVisible.value = false
  closeContextMenu()
}

// 底部工具栏 — 原生 HTML5 drag
const onDragStart = (event: DragEvent, node_type: NodeType) => {
  if (event.dataTransfer) {
    event.dataTransfer.setData('application/vueflow', node_type)
    event.dataTransfer.effectAllowed = 'move'
  }
}
const onDragOver = (event: DragEvent) => {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}
const onDrop = (event: DragEvent) => {
  const node_type = event.dataTransfer?.getData('application/vueflow') as NodeType | undefined
  if (!node_type) return
  addNode(node_type, event.clientX, event.clientY)
}

// 浮动面板列表项 — mousedown 模拟拖拽
const onItemMouseDown = (event: MouseEvent, meta: (typeof NODE_META_LIST)[0]) => {
  event.preventDefault()
  event.stopPropagation()
  isDraggingItem.value = true
  draggingNodeType.value = meta.type
  ghost.value = {
    visible: true,
    x: event.clientX + 12,
    y: event.clientY + 12,
    label: meta.label,
    colorClass: meta.colorClass,
    icon: meta.icon,
  }
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'grabbing'
}

const onGlobalMouseMove = (event: MouseEvent) => {
  if (isPanelDragging.value) {
    const vw = window.innerWidth
    const vh = window.innerHeight
    let x = event.clientX - panelDragOffset.value.x
    let y = event.clientY - panelDragOffset.value.y
    x = Math.max(PANEL_MARGIN, Math.min(x, vw - PANEL_WIDTH - PANEL_MARGIN))
    y = Math.max(PANEL_MARGIN, Math.min(y, vh - PANEL_MARGIN))
    addNodePanelPos.value = { x, y }
  }
  if (isDraggingItem.value) {
    ghost.value.x = event.clientX + 12
    ghost.value.y = event.clientY + 12
  }
}

const onGlobalMouseUp = (event: MouseEvent) => {
  isPanelDragging.value = false
  if (isDraggingItem.value) {
    isDraggingItem.value = false
    ghost.value.visible = false
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    const node_type = draggingNodeType.value
    draggingNodeType.value = ''
    if (!node_type) return
    const panel = document.querySelector('.add-node-panel') as HTMLElement | null
    if (panel) {
      const panelRect = panel.getBoundingClientRect()
      const inPanel =
        event.clientX >= panelRect.left &&
        event.clientX <= panelRect.right &&
        event.clientY >= panelRect.top &&
        event.clientY <= panelRect.bottom
      if (inPanel) return
    }

    const canvas = document.querySelector('.vue-flow__pane') as HTMLElement | null
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const inCanvas =
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom
    if (inCanvas) addNode(node_type as NodeType, event.clientX, event.clientY)
  }
}

onConnect((connection) => {
  const { source, target } = connection
  if (source === target) {
    Message.error('不能将节点连接到本身')
    return
  }
  if (
    (edges.value as FlowEdge[]).some(
      (e) =>
        (e.source === source && e.target === target) ||
        (e.source === target && e.target === source),
    )
  ) {
    Message.error('这两个节点已有连接，无需重复添加')
    return
  }
  const source_node = findNode(source)
  const target_node = findNode(target)
  saveHistory()
  edges.value.push({
    ...connection,
    id: crypto.randomUUID(),
    source_type: source_node?.type as NodeType | undefined,
    target_type: target_node?.type as NodeType | undefined,
    style: { strokeWidth: 2, stroke: '#9ca3af' },
  } as Edge)
})

onPaneReady((vueFlowInstance) => {
  instance.value = vueFlowInstance
})

const onChange = () => {
  // 初始化、手动保存中、调试运行中时均跳过自动保存
  // isDebugging 防止节点 class（错误红框）变化触发保存请求和"更新成功"提示
  if (isInitializing.value || isSaving.value || isDebugging.value) return
  handleUpdateDraftGraph(
    String(route.params?.workflow_id ?? ''),
    convertGraphToReq(nodes.value, edges.value),
  )
}

const saveGraph = async (showMsg = false) => {
  isSaving.value = true
  await handleUpdateDraftGraph(
    String(route.params?.workflow_id ?? ''),
    convertGraphToReq(nodes.value, edges.value),
    showMsg,
  )
  isSaving.value = false
}

const onUpdateNode = (node_data: Partial<NodeData> & { id: string }) => {
  const idx = nodes.value.findIndex((item) => item.id === node_data.id)
  if (idx !== -1 && nodes.value[idx]?.data)
    nodes.value[idx].data = { ...nodes.value[idx].data, ...node_data }
  handleUpdateDraftGraph(
    String(route.params?.workflow_id ?? ''),
    convertGraphToReq(nodes.value, edges.value),
    true,
  )
}

const onCloseNodeInfo = () => {
  nodeInfoVisible.value = false
  selectedNode.value = null
  removeSelectedNodes(allNodes.value)
}

const closeContextMenu = () => {
  contextMenu.value.visible = false
}

onNodeContextMenu((nodeMouseEvent) => {
  nodeMouseEvent.event.preventDefault()
  isNodeContextMenuFired.value = true
  addNodePanelVisible.value = false
  contextMenu.value.visible = true
  contextMenu.value.isNodeMenu = true
  contextMenu.value.isEdgeMenu = false
  contextMenu.value.nodeId = nodeMouseEvent.node.id
  contextMenu.value.nodeTitle = nodeMouseEvent.node.data?.title ?? '该节点'
  updateContextMenuPosition(
    (nodeMouseEvent.event as MouseEvent).clientX,
    (nodeMouseEvent.event as MouseEvent).clientY,
  )
})

const onCanvasContextMenu = (event: MouseEvent) => {
  if (isNodeContextMenuFired.value) {
    isNodeContextMenuFired.value = false
    return
  }
  event.preventDefault()
  addNodePanelVisible.value = false
  contextMenu.value.visible = true
  contextMenu.value.isNodeMenu = false
  contextMenu.value.isEdgeMenu = false
  contextMenu.value.nodeId = ''
  contextMenu.value.nodeTitle = ''
  updateContextMenuPosition(event.clientX, event.clientY)
}

// 删除节点后清理残留引用：各节点入参/结束节点出参中引用已删节点的变量自动移除
const cleanupStaleRefs = (deletedIds: Set<string>) => {
  nodes.value = (nodes.value as FlowNode[]).map((n) => {
    const key = n.type === 'end' ? 'outputs' : 'inputs'
    const vars = n.data?.[key] as
      | Array<{ value?: { type?: string; content?: { ref_node_id?: string } } }>
      | undefined
    if (!vars || vars.length === 0) return n
    const kept = vars.filter((v) => {
      const value = v.value
      const refId = (value?.content as { ref_node_id?: string } | undefined)?.ref_node_id
      return !(value?.type === 'ref' && refId && deletedIds.has(refId))
    })
    if (kept.length === vars.length) return n
    return { ...n, data: { ...(n.data ?? {}), [key]: kept } }
  })
}

const deleteNode = () => {
  saveHistory()
  const selectedIds = new Set(
    (nodes.value as FlowNode[]).filter((n) => n.selected).map((n) => n.id),
  )
  const idsToDelete = selectedIds.size > 0 ? selectedIds : new Set([contextMenu.value.nodeId])
  nodes.value = (nodes.value as FlowNode[]).filter((n) => !idsToDelete.has(n.id))
  edges.value = (edges.value as FlowEdge[]).filter(
    (e) => !idsToDelete.has(e.source) && !idsToDelete.has(e.target),
  ) as unknown as Edge[]
  // 清理剩余节点中指向已删节点的引用（含结束节点出参）
  cleanupStaleRefs(idsToDelete)
  if (selectedNode.value && idsToDelete.has(selectedNode.value.id)) onCloseNodeInfo()
  closeContextMenu()
  saveGraph()
}

const deleteEdge = () => {
  const id = contextMenu.value.isEdgeMenu ? contextMenu.value.nodeId : selectedEdgeId.value
  if (!id) return
  saveHistory()
  edges.value = (edges.value as FlowEdge[]).filter((e) => e.id !== id) as unknown as Edge[]
  selectedEdgeId.value = ''
  closeContextMenu()
  saveGraph()
}

// 全选节点 (Ctrl+A) — 仅在画布焦点下触发
const selectAllNodes = () => {
  nodes.value = (nodes.value as FlowNode[]).map((n) => ({ ...n, selected: true }))
}

// 删除选中节点（键盘 Delete / Backspace）
const deleteSelectedNodes = () => {
  const selectedIds = new Set(
    (nodes.value as FlowNode[]).filter((n) => n.selected).map((n) => n.id),
  )
  if (selectedIds.size === 0) return
  saveHistory()
  nodes.value = (nodes.value as FlowNode[]).filter((n) => !selectedIds.has(n.id))
  edges.value = (edges.value as FlowEdge[]).filter(
    (e) => !selectedIds.has(e.source) && !selectedIds.has(e.target),
  ) as unknown as Edge[]
  // 清理剩余节点中指向已删节点的引用（含结束节点出参）
  cleanupStaleRefs(selectedIds)
  if (selectedNode.value && selectedIds.has(selectedNode.value.id)) onCloseNodeInfo()
  saveGraph()
}

// --- 复制粘贴 ---
const clipboard = ref<FlowNode[]>([])

const UNCOPYABLE_TYPES: NodeType[] = ['start', 'end']

/**
 * 判断当前焦点是否在可编辑区域（输入框、弹窗内容区等）
 * 用于决定键盘快捷键是否交给浏览器默认行为处理
 */
const isFocusInEditable = () => {
  const el = document.activeElement
  if (!el || el === document.body) return false
  const tag = el.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea') return true
  if ((el as HTMLElement).isContentEditable) return true
  if ((el as HTMLElement).closest('.arco-modal-wrapper, .arco-drawer-wrapper, .arco-trigger-popup'))
    return true
  return false
}

/**
 * 判断当前是否有弹出层（Modal / Drawer / 下拉面板等）处于打开状态
 * 当弹出层打开时，Ctrl+A 应交给弹出层内部处理，不拦截为"全选画布节点"
 */
const isOverlayOpen = () => {
  return !!(
    document.querySelector('.arco-modal-wrapper') ||
    document.querySelector('.arco-drawer-wrapper') ||
    document.querySelector('.arco-trigger-popup') ||
    document.querySelector('[role="dialog"]') ||
    document.querySelector('[role="alertdialog"]')
  )
}

const copyNodes = (explicitNodeId?: string) => {
  // 焦点在编辑区时不处理，交给浏览器
  if (isFocusInEditable()) return

  // 优先复制画布上的选中文字
  const selectedText = window.getSelection()?.toString()
  if (selectedText) {
    navigator.clipboard.writeText(selectedText)
    return
  }

// explicitNodeId 存在（右键菜单点击路径）→ 直接用，完全无视 selected 状态
  //    这样即使上次粘贴留下了 selected 节点，也不会影响右键复制的目标
// 无显式 ID（Ctrl+C 键盘路径）→ 多选节点 → contextMenu.nodeId → selectedNode 兜底
  let targetNodes: FlowNode[] = []

  if (explicitNodeId) {
    targetNodes = (nodes.value as FlowNode[]).filter(
      (n) => n.id === explicitNodeId && !UNCOPYABLE_TYPES.includes(n.type),
    )
    if (targetNodes.length === 0) {
      Message.warning('开始节点和结束节点不支持复制')
      return
    }
  } else {
    const selectedNodes = (nodes.value as FlowNode[]).filter(
      (n) => n.selected && !UNCOPYABLE_TYPES.includes(n.type),
    )
    const contextNodeId = contextMenu.value.nodeId
    if (selectedNodes.length > 0) {
      targetNodes = selectedNodes
    } else if (contextNodeId) {
      targetNodes = (nodes.value as FlowNode[]).filter(
        (n) => n.id === contextNodeId && !UNCOPYABLE_TYPES.includes(n.type),
      )
      if (targetNodes.length === 0) {
        Message.warning('开始节点和结束节点不支持复制')
        return
      }
    } else if (selectedNode.value) {
      if (!UNCOPYABLE_TYPES.includes(selectedNode.value.type)) {
        targetNodes = [selectedNode.value]
      } else {
        Message.warning('开始节点和结束节点不支持复制')
        return
      }
    } else {
      const hasUncopyable = (nodes.value as FlowNode[]).some(
        (n) => n.selected && UNCOPYABLE_TYPES.includes(n.type),
      )
      if (hasUncopyable) Message.warning('开始节点和结束节点不支持复制')
      return
    }
  }

  clipboard.value = JSON.parse(JSON.stringify(targetNodes))
  Message.success(`已复制 ${targetNodes.length} 个节点`)
  closeContextMenu()
}

// 通用复制选中文字
const copySelectedText = () => {
  const text = window.getSelection()?.toString()
  if (text) {
    navigator.clipboard.writeText(text).then(() => Message.success('已复制'))
  } else {
    Message.warning('没有选中任何文字')
  }
  closeContextMenu()
}

const hasSelectedText = computed(() => contextMenuSelectedText.value.length > 0)

const pasteNodes = () => {
  if (clipboard.value.length === 0) return
  const pasteable = clipboard.value.filter((n) => !UNCOPYABLE_TYPES.includes(n.type))
  if (pasteable.length === 0) return
  saveHistory()
  const offset = 30
  const newNodes = pasteable.map((n) => ({
    ...n,
    id: v4(),
    selected: false,
    position: {
      x: n.position.x + offset,
      y: n.position.y + offset,
    },
    data: {
      ...n.data,
      title: `${n.data.title}-副本`,
    },
  }))
  nodes.value = (nodes.value as FlowNode[]).map((n) => ({ ...n, selected: false }))
  nodes.value.push(...newNodes)
  clipboard.value = JSON.parse(JSON.stringify(newNodes))
}

// 监听连线选中态，动态更新连线样式
watch(selectedEdgeId, (newId, oldId) => {
  edges.value = (edges.value as FlowEdge[]).map((e) => {
    if (e.id === oldId) {
      return { ...e, style: { strokeWidth: 2, stroke: '#9ca3af' } }
    }
    if (e.id === newId) {
      return { ...e, style: { strokeWidth: 2.5, stroke: '#3b82f6' } }
    }
    return e
  }) as unknown as Edge[]
})

// 键盘事件处理
const onKeyDown = (e: KeyboardEvent) => {
  const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
  const isEditable =
    tag === 'input' || tag === 'textarea' || (e.target as HTMLElement)?.isContentEditable
  if (isEditable) return

  // Ctrl+Z 撤销
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z') {
    e.preventDefault()
    undo()
    return
  }

  // Ctrl+Shift+Z 或 Ctrl+Y 重做
  if (
    ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'z') ||
    ((e.ctrlKey || e.metaKey) && e.key === 'y')
  ) {
    e.preventDefault()
    redo()
    return
  }

  // Ctrl+C 复制
  if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
    // 焦点在编辑区时交给浏览器默认复制
    if (isFocusInEditable()) return
    const selectedText = window.getSelection()?.toString()
    // 有文字选区时交给浏览器默认复制
    if (selectedText) return
    e.preventDefault()
    copyNodes()
    return
  }

  // Ctrl+V 粘贴
  if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
    // 焦点在编辑区时交给浏览器默认粘贴
    if (isFocusInEditable()) return
    e.preventDefault()
    pasteNodes()
    return
  }

  // Ctrl+A 全选
  // 让焦点所在的弹出层组件自行处理全选（如全选输入框内容）。
  // 只有在纯画布状态下（无弹出层、焦点不在编辑区）才执行"全选节点"。
  if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
    // 焦点明确在编辑区时交给浏览器
    if (isFocusInEditable()) return
    // 有弹出层打开时，不拦截，让弹出层内部自行处理
    if (isOverlayOpen()) return
    e.preventDefault()
    selectAllNodes()
    return
  }

  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (selectedEdgeId.value) {
      deleteEdge()
    } else {
      deleteSelectedNodes()
    }
  }
}

const refreshPage = () => {
  closeContextMenu()
  window.location.reload()
}

const onZoomSelect = (value: number) => {
  zoomLevel.value = value
  instance.value?.zoomTo(value)
}

const centerFit = async () => {
  if (instance.value) {
    await instance.value.zoomTo(1)
  }
  await nextTick()
  await fitView({ padding: 0.2 })
}

const openAddNodePanel = () => {
  addNodePanelVisible.value = true
  const vw = window.innerWidth
  const vh = window.innerHeight
  const menuX = contextMenu.value.x
  const menuY = contextMenu.value.y
  let x = menuX + 8
  if (x + PANEL_WIDTH + PANEL_MARGIN > vw) x = menuX - PANEL_WIDTH - 8
  x = Math.max(PANEL_MARGIN, x)
  let y = menuY
  if (y + PANEL_HEIGHT + PANEL_MARGIN > vh) y = vh - PANEL_HEIGHT - PANEL_MARGIN
  y = Math.max(PANEL_MARGIN, y)
  addNodePanelPos.value = { x, y }
  closeContextMenu()
}

onPaneClick(() => {
  selectedNode.value = null
  nodeInfoVisible.value = false
  selectedEdgeId.value = ''
  removeSelectedNodes(allNodes.value)
  closeContextMenu()
  addNodePanelVisible.value = false
})

onEdgeClick((edgeMouseEvent) => {
  selectedNode.value = null
  nodeInfoVisible.value = false
  removeSelectedNodes(allNodes.value)
  closeContextMenu()
  addNodePanelVisible.value = false
  const clickedId = edgeMouseEvent.edge.id
  if (selectedEdgeId.value === clickedId) {
    selectedEdgeId.value = ''
  } else {
    selectedEdgeId.value = clickedId
  }
})

// 连线右键菜单
onEdgeContextMenu((edgeMouseEvent) => {
  edgeMouseEvent.event.preventDefault()
  isNodeContextMenuFired.value = true
  selectedEdgeId.value = edgeMouseEvent.edge.id
  addNodePanelVisible.value = false
  contextMenu.value.visible = true
  contextMenu.value.isNodeMenu = false
  contextMenu.value.isEdgeMenu = true
  contextMenu.value.nodeId = edgeMouseEvent.edge.id
  contextMenu.value.nodeTitle = ''
  updateContextMenuPosition(
    (edgeMouseEvent.event as MouseEvent).clientX,
    (edgeMouseEvent.event as MouseEvent).clientY,
  )
})

onNodeClick((nodeMouseEvent) => {
  // Ctrl/Meta 多选时不打开详情面板
  if (nodeMouseEvent.event.ctrlKey || nodeMouseEvent.event.metaKey) {
    closeContextMenu()
    addNodePanelVisible.value = false
    return
  }
  if (!selectedNode.value || selectedNode.value?.id !== nodeMouseEvent.node.id) {
    selectedNode.value = nodeMouseEvent.node as unknown as FlowNode
    nodeInfoVisible.value = true
  }
  closeContextMenu()
  addNodePanelVisible.value = false
})

onNodeDragStop(() => {
  saveHistory()
  saveGraph()
})

onViewportChange((viewportTransform) => {
  zoomLevel.value = viewportTransform.zoom
})

const onPanelHeaderMouseDown = (event: MouseEvent) => {
  isPanelDragging.value = true
  panelDragOffset.value = {
    x: event.clientX - addNodePanelPos.value.x,
    y: event.clientY - addNodePanelPos.value.y,
  }
  event.preventDefault()
}

onMounted(async () => {
  const workflow_id = String(route.params?.workflow_id ?? '')
  await loadWorkflow(workflow_id)
  await loadDraftGraph(workflow_id)
  await nextTick()
  isInitializing.value = false
  setTimeout(async () => {
    if (instance.value) {
      await instance.value.zoomTo(1)
    }
    await fitView({ padding: 0.2 })
  }, 100)
  document.addEventListener('click', closeContextMenu)
  document.addEventListener('mousemove', onGlobalMouseMove)
  document.addEventListener('mouseup', onGlobalMouseUp)
  document.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', closeContextMenu)
  document.removeEventListener('mousemove', onGlobalMouseMove)
  document.removeEventListener('mouseup', onGlobalMouseUp)
  document.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <div class="min-h-screen flex flex-col h-full overflow-hidden relative">
    <!-- 顶部 Header -->
    <div
      class="h-[77px] shrink-0 bg-white p-4 flex items-center justify-between relative border-b"
    >
      <div class="flex items-center gap-2">
        <router-link :to="{ name: 'space-workflows-list' }">
          <a-button aria-label="返回" size="mini">
            <template #icon><icon-left /></template>
          </a-button>
        </router-link>
        <div class="flex items-center gap-3">
          <a-avatar :size="40" shape="square" class="rounded-lg" :image-url="workflow.icon" />
          <div class="flex flex-col justify-between h-[40px]">
            <a-skeleton-line v-if="getWorkflowLoading" :widths="[100]" />
            <div v-else class="text-gray-700 font-bold">{{ workflow.name }}</div>
            <div v-if="getWorkflowLoading" class="flex items-center gap-2">
              <a-skeleton-line :widths="[60]" :line-height="18" />
              <a-skeleton-line :widths="[60]" :line-height="18" />
              <a-skeleton-line :widths="[60]" :line-height="18" />
            </div>
            <div v-else class="flex items-center gap-2">
              <div class="max-w-[160px] line-clamp-1 text-xs text-gray-500">
                {{ workflow.description }}
              </div>
              <div class="flex items-center h-[18px] text-xs text-gray-500">
                <icon-schedule />{{ workflow.status === 'draft' ? '草稿' : '已发布' }}
              </div>
              <a-tag size="small" class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500">
                已自动保存
                {{ moment((workflow.updated_at ?? 0) * 1000).format('HH:mm:ss') }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>
      <a-space :size="12">
        <a-button-group>
          <a-button
            :disabled="!workflow.is_debug_passed"
            :loading="publishWorkflowLoading"
            @click="handlePublishWorkflow(String(workflow.id))"
            type="primary"
            class="rounded-tl-lg rounded-bl-lg"
          >
            更新发布
          </a-button>
          <a-dropdown position="br">
            <a-button aria-label="下载"
              :disabled="workflow.status !== 'published'"
              type="primary"
              class="rounded-tr-lg rounded-br-lg !w-5"
            >
              <template #icon><icon-down /></template>
            </a-button>
            <template #content>
              <a-doption
                :disabled="workflow.status !== 'published'"
                @click="() => handleCancelPublish(String(workflow.id))"
                class="!text-red-700"
              >
                取消发布
              </a-doption>
            </template>
          </a-dropdown>
        </a-button-group>
      </a-space>
    </div>

    <!-- 中间编排画布 -->
    <div class="flex-1">
      <vue-flow
        :min-zoom="0.25"
        :max-zoom="2"
        :nodes-connectable="true"
        :connection-mode="ConnectionMode.Strict"
        :connection-line-options="{ style: { strokeWidth: 2, stroke: '#9ca3af' } }"
        :node-types="NODE_TYPES"
        v-model:nodes="nodes"
        v-model:edges="edges"
        @update:nodes="onChange"
        @update:edges="onChange"
        @drop="onDrop"
        @dragover="onDragOver"
        @contextmenu="onCanvasContextMenu"
      >
        <background />
        <mini-map
          class="rounded-xl border border-gray-300 overflow-hidden !left-0 right-auto!"
          :width="316"
          :height="190"
          pannable
          zoomable
        />

        <panel position="bottom-center">
          <div class="p-[5px] bg-white rounded-xl border z-50">
            <a-space :size="8">
              <template #split><a-divider direction="vertical" class="m-0" /></template>
              <!-- 节点按钮：悬浮下拉（原效果，含展示方式选择） -->
              <a-trigger
                v-if="nodeListMode === 'dropdown'"
                position="top"
                :popup-translate="[0, -16]"
              >
                <a-button type="primary" class="!rounded-lg px-2">
                  <template #icon><icon-plus-circle-fill /></template>
                  节点
                </a-button>
                <template #content>
                  <div
                    class="bg-white border border-gray-200 w-[280px] shadow rounded-xl overflow-hidden py-2"
                  >
                    <!-- 展示方式选择（仅选项，居中不换行） -->
                    <div
                      class="px-3 pb-2 border-b border-gray-100 mb-1 flex items-center justify-center"
                    >
                      <a-radio-group
                        size="mini"
                        class="whitespace-nowrap"
                        :model-value="nodeListMode"
                        @update:model-value="(v) => switchNodeListMode(v as 'dropdown' | 'left')"
                      >
                        <a-radio value="dropdown">悬浮列表</a-radio>
                        <a-radio value="left">固定左侧</a-radio>
                      </a-radio-group>
                    </div>
                    <div
                      v-for="meta in NODE_META_LIST"
                      :key="meta.type"
                      class="flex flex-col px-3 py-2 gap-2 cursor-grab hover:bg-gray-50 active:cursor-grabbing"
                      draggable="true"
                      @dragstart="onDragStart($event, meta.type as NodeType)"
                      @click="addNode(meta.type as NodeType)"
                    >
                      <div class="flex items-center gap-2">
                        <a-avatar
                          shape="square"
                          :size="24"
                          :class="`${meta.colorClass} rounded-lg`"
                        >
                          <component :is="`icon-${meta.icon}`" />
                        </a-avatar>
                        <div class="text-gray-700 font-semibold">{{ meta.label }}</div>
                      </div>
                      <div class="text-gray-500 text-xs">{{ meta.desc }}</div>
                    </div>
                  </div>
                </template>
              </a-trigger>
              <!-- 节点按钮：固定左侧面板模式（点击切换开/关） -->
              <a-button
                v-else
                type="primary"
                class="!rounded-lg px-2"
                @click="nodePanelVisible = !nodePanelVisible"
              >
                <template #icon><icon-plus-circle-fill /></template>
                节点
              </a-button>
              <div class="flex items-center gap-3">
                <a-tooltip content="自适应布局">
                  <a-button aria-label="应用"
                    size="small"
                    type="text"
                    class="!text-gray-700 rounded-lg"
                    @click="centerFit"
                  >
                    <template #icon><icon-apps /></template>
                  </a-button>
                </a-tooltip>
                <a-dropdown trigger="hover" @select="(value) => onZoomSelect(Number(value))">
                  <a-button size="small" class="!text-gray-700 px-2 rounded-lg gap-1 w-[80px]">
                    {{ (zoomLevel * 100).toFixed(0) }}%
                    <icon-down />
                  </a-button>
                  <template #content>
                    <a-doption
                      v-for="zoom in zoomOptions"
                      :key="zoom.value"
                      :value="zoom.value"
                      class="w-[80px]"
                    >
                      {{ zoom.label }}
                    </a-doption>
                  </template>
                </a-dropdown>
              </div>
              <a-button type="text" size="small" class="px-2 rounded-lg" @click="openDebugModal()">
                <template #icon><icon-play-arrow /></template>
                调试
              </a-button>
            </a-space>
          </div>
        </panel>

        <debug-modal
          :workflow_id="String(route.params?.workflow_id ?? '')"
          :node_ids="debugTargetNodeIds"
          v-model:visible="debugModalVisible"
          @node-status="setNodeStatus"
          @clear-errors="clearNodeStatuses"
          @debug-start="isDebugging = true"
          @debug-end="isDebugging = false"
        />

        <node-list-panel
          :visible="nodePanelVisible"
          :meta-list="NODE_META_LIST"
          @update:visible="nodePanelVisible = $event"
          @add-node="(type: string) => addNode(type as NodeType)"
          @drag-start="onDragStart"
          @switch-mode="switchNodeListMode"
        />

        <!-- 详情面板组件 -->
        <start-node-info
          v-if="selectedNode && selectedNode?.type === 'start'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <l-l-m-node-info
          v-if="selectedNode && selectedNode?.type === 'llm'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <template-transform-info
          v-if="selectedNode && selectedNode?.type === 'template_transform'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <code-node-info
          v-if="selectedNode && selectedNode?.type === 'code'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <http-request-node-info
          v-if="selectedNode && selectedNode?.type === 'http_request'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <dataset-retrieval-node-info
          v-if="selectedNode && selectedNode?.type === 'dataset_retrieval'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <tool-node-info
          v-if="selectedNode && selectedNode?.type === 'tool'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
        <end-node-info
          v-if="selectedNode && selectedNode?.type === 'end'"
          :loading="updateDraftGraphLoading"
          :node="selectedNode"
          :visible="nodeInfoVisible"
          @update:visible="onCloseNodeInfo"
          @update-node="onUpdateNode"
        />
      </vue-flow>
    </div>

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="context-menu"
        :style="{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }"
        @click.stop
        @contextmenu.prevent
      >
        <template v-if="contextMenu.isNodeMenu">
          <div class="context-menu-title">{{ contextMenu.nodeTitle }}</div>
          <div class="context-menu-divider" />
        </template>
        <!-- 撤销/重做 -->
        <div
          class="context-menu-item"
          :class="{ 'context-menu-item--disabled': !canUndo }"
          @click="canUndo && undo()"
        >
          <icon-undo :size="14" />
          <span>撤销</span>
          <span class="ml-auto text-[11px] text-gray-400">Ctrl+Z</span>
        </div>
        <div
          class="context-menu-item"
          :class="{ 'context-menu-item--disabled': !canRedo }"
          @click="canRedo && redo()"
        >
          <icon-redo :size="14" />
          <span>重做</span>
          <span class="ml-auto text-[11px] text-gray-400">Ctrl+Shift+Z</span>
        </div>
        <div class="context-menu-divider" />
        <div class="context-menu-item" @click.stop="openAddNodePanel">
          <icon-plus :size="14" /><span>添加节点</span>
          <icon-right :size="12" class="ml-auto !text-gray-400" />
        </div>
        <div class="context-menu-item" @click="refreshPage">
          <icon-refresh :size="14" /><span>刷新页面</span>
        </div>
        <div class="context-menu-divider" />
        <template v-if="contextMenu.isNodeMenu">
          <div class="context-menu-item" @click="handleDebugNode">
            <icon-play-arrow :size="14" /><span>调试该节点</span>
          </div>
          <div
            class="context-menu-item"
            @click="
              () => {
                copyNodes(contextMenu.nodeId)
              }
            "
          >
            <icon-copy :size="14" /><span>复制节点</span>
            <span class="ml-auto text-[11px] text-gray-400">Ctrl+C</span>
          </div>
        </template>
        <template v-else-if="!contextMenu.isEdgeMenu">
          <div
            class="context-menu-item"
            :class="{ 'context-menu-item--disabled': !hasSelectedText }"
            @click="copySelectedText"
          >
            <icon-copy :size="14" /><span>复制</span>
          </div>
        </template>
        <div
          class="context-menu-item"
          :class="{ 'context-menu-item--disabled': clipboard.length === 0 }"
          @click="clipboard.length > 0 && (pasteNodes(), closeContextMenu())"
        >
          <icon-paste :size="14" /><span>粘贴节点</span>
          <span class="ml-auto text-[11px] text-gray-400">Ctrl+V</span>
        </div>
        <div class="context-menu-divider" />
        <div class="context-menu-label">
          {{
            (nodes as FlowNode[]).filter((n) => n.selected).length > 0
              ? '排列选中节点'
              : '自动排列全图'
          }}
        </div>
        <div
          v-for="opt in layoutOptions"
          :key="opt.value"
          class="context-menu-item context-menu-item--small"
          @click="autoLayout(opt.value)"
        >
          <component :is="opt.icon" :size="13" /><span>{{ opt.label }}</span>
        </div>
        <template v-if="contextMenu.isEdgeMenu">
          <div class="context-menu-divider" />
          <div class="context-menu-item context-menu-item--danger" @click="deleteEdge">
            <icon-delete :size="14" /><span>删除连线</span>
          </div>
        </template>
        <template v-if="contextMenu.isNodeMenu">
          <div class="context-menu-divider" />
          <div class="context-menu-item context-menu-item--danger" @click="deleteNode">
            <icon-delete :size="14" />
            <span>
              {{
                (nodes as FlowNode[]).filter((n) => n.selected).length > 1
                  ? `删除选中节点 (${(nodes as FlowNode[]).filter((n) => n.selected).length})`
                  : '删除节点'
              }}
            </span>
          </div>
        </template>
      </div>
    </Teleport>

    <!-- 添加节点浮动面板 -->
    <Teleport to="body">
      <div
        v-if="addNodePanelVisible"
        class="add-node-panel"
        :style="{ top: `${addNodePanelPos.y}px`, left: `${addNodePanelPos.x}px` }"
        @click.stop
        @contextmenu.prevent
      >
        <div class="add-node-panel-header" @mousedown="onPanelHeaderMouseDown">
          <div class="flex items-center gap-2">
            <icon-drag-dot class="!text-gray-400" style="font-size: 13px" />
            <icon-plus-circle class="!text-blue-600" />
            <span class="font-semibold text-gray-700 text-sm">添加节点</span>
          </div>
          <button aria-label="关闭" class="add-node-panel-close" @mousedown.stop @click="addNodePanelVisible = false">
            <icon-close :size="14" />
          </button>
        </div>
        <div class="add-node-panel-divider" />
        <div class="add-node-panel-list">
          <div
            v-for="meta in NODE_META_LIST"
            :key="meta.type"
            class="add-node-panel-item"
            @mousedown="onItemMouseDown($event, meta)"
            @click="addNodeFromPanel(meta.type as NodeType)"
          >
            <div :class="`add-node-panel-icon ${meta.colorClass}`">
              <component :is="`icon-${meta.icon}`" style="font-size: 13px; color: white" />
            </div>
            <div class="flex flex-col gap-0.5 flex-1 min-w-0">
              <div class="text-gray-700 text-xs font-semibold leading-tight">{{ meta.label }}</div>
              <div class="text-gray-400 text-[11px] leading-tight line-clamp-1">
                {{ meta.desc }}
              </div>
            </div>
            <icon-drag-dot :size="13" class="!text-gray-300 shrink-0" />
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 拖拽 Ghost 跟随预览 -->
    <Teleport to="body">
      <div
        v-if="ghost.visible"
        class="drag-ghost"
        :style="{ top: `${ghost.y}px`, left: `${ghost.x}px` }"
      >
        <div :class="`drag-ghost-icon ${ghost.colorClass}`">
          <component :is="`icon-${ghost.icon}`" style="font-size: 14px; color: white" />
        </div>
        <span class="drag-ghost-label">{{ ghost.label }}</span>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
@reference "../../../assets/styles/index.css";
.selected .vue-flow__edge-path {
  @apply stroke-blue-700!;
}
.cursor-grab {
  cursor: grab;
}
.active\:cursor-grabbing:active {
  cursor: grabbing;
}
</style>

<style>
/**
 * 调试节点状态样式
 * VueFlow 将 node.class 挂到 .vue-flow__node 元素上
 */
/* 成功：绿色边框（替代原右上角对勾徽标） */
.vue-flow__node.node-status-succeeded {
  border-radius: 12px;
  outline: 2.5px solid #22c55e;
  outline-offset: 2px;
  box-shadow:
    0 0 0 4px rgba(34, 197, 94, 0.15),
    0 4px 16px rgba(34, 197, 94, 0.2);
}

/* 失败：红框脉冲 */
.vue-flow__node.node-status-failed {
  border-radius: 12px;
  outline: 2.5px solid #ef4444;
  outline-offset: 2px;
  box-shadow:
    0 0 0 4px rgba(239, 68, 68, 0.15),
    0 4px 16px rgba(239, 68, 68, 0.2);
  animation: nodeErrorPulse 1.8s ease-in-out infinite;
}

@keyframes nodeErrorPulse {
  0%,
  100% {
    box-shadow:
      0 0 0 3px rgba(239, 68, 68, 0.12),
      0 4px 16px rgba(239, 68, 68, 0.15);
  }
  50% {
    box-shadow:
      0 0 0 6px rgba(239, 68, 68, 0.22),
      0 4px 20px rgba(239, 68, 68, 0.3);
  }
}

/* 跳过：灰化 + 虚线描边 */
.vue-flow__node.node-status-skipped {
  opacity: 0.65;
  outline: 1.5px dashed #9ca3af;
  outline-offset: 2px;
}

/* 运行中：蓝色描边 */
.vue-flow__node.node-status-running {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}
</style>

<style>
/* ── 右键菜单 ── */
.context-menu {
  position: fixed;
  z-index: 9999;
  min-width: 170px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow:
    0 8px 24px rgba(0, 0, 0, 0.1),
    0 2px 6px rgba(0, 0, 0, 0.06);
  padding: 4px;
  user-select: none;
}
.context-menu-title,
.context-menu-label {
  padding: 6px 12px 4px;
  font-size: 11px;
  color: #9ca3af;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.context-menu-divider {
  height: 1px;
  background: #f3f4f6;
  margin: 4px 0;
}
.context-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  color: #374151;
  transition: background 0.15s;
}
.context-menu-item:hover {
  background: #f9fafb;
}
.context-menu-item--small {
  padding: 5px 12px;
  font-size: 12px;
}
.context-menu-item--danger {
  color: #dc2626;
}
.context-menu-item--danger:hover {
  background: #fef2f2;
}
.context-menu-item--disabled {
  color: #d1d5db !important;
  cursor: not-allowed;
}
.context-menu-item--disabled:hover {
  background: transparent;
}

/* ── 添加节点浮动面板 ── */
.add-node-panel {
  position: fixed;
  z-index: 9998;
  width: 232px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow:
    0 12px 32px rgba(0, 0, 0, 0.12),
    0 2px 8px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: panelFadeIn 0.18s ease;
  max-height: min(480px, calc(100vh - 16px));
}
@keyframes panelFadeIn {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(-4px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}
.add-node-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  cursor: grab;
  user-select: none;
  background: #fafafa;
  border-bottom: 1px solid #f3f4f6;
  flex-shrink: 0;
}
.add-node-panel-header:active {
  cursor: grabbing;
}
.add-node-panel-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}
.add-node-panel-close:hover {
  background: #f3f4f6;
}
.add-node-panel-divider {
  height: 1px;
  background: #f3f4f6;
  flex-shrink: 0;
}
.add-node-panel-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.add-node-panel-list::-webkit-scrollbar {
  width: 4px;
}
.add-node-panel-list::-webkit-scrollbar-thumb {
  background: #e5e7eb;
  border-radius: 4px;
}
.add-node-panel-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 9px;
  border-radius: 8px;
  cursor: grab;
  transition: background 0.15s;
  user-select: none;
}
.add-node-panel-item:hover {
  background: #f9fafb;
}
.add-node-panel-item:active {
  cursor: grabbing;
}
.add-node-panel-item:hover .add-node-panel-icon {
  filter: brightness(1.08);
}
.add-node-panel-icon {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: filter 0.15s;
}

/* ── 拖拽 Ghost ── */
.drag-ghost {
  position: fixed;
  z-index: 99999;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 6px 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.14);
  opacity: 0.9;
  transform: rotate(2deg);
  white-space: nowrap;
}
.drag-ghost-icon {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.drag-ghost-label {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}
</style>
