import { ref } from 'vue'
import type {
  CreateWorkflowRequest,
  DraftGraphEdge,
  DraftGraphNode,
  GetWorkflowResponse,
  GetWorkflowsWithPageResponse,
  UpdateDraftGraphRequest,
  UpdateWorkflowRequest,
} from '@/models/workflow.ts'
import type { Edge, Node } from '@vue-flow/core'
import {
  cancelPublishWorkflow,
  createWorkflow,
  debugWorkflow,
  deleteWorkflow,
  getDraftGraph,
  getWorkflow,
  getWorkflowsWithPage,
  publishWorkflow,
  updateDraftGraph,
  updateWorkflow,
} from '@/services/workflow.ts'
import { useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'

export const useGetWorkflowsWithPage = () => {
  const loading = ref(false)
  const workflows = ref<GetWorkflowsWithPageResponse['data']['list']>([])
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref({ ...defaultPaginator })

  const loadWorkflows = async (
    search_word: string = '',
    status: string = '',
    init: boolean = false,
  ) => {
// 判断是否是初始化，并检查分页器
    if (init) {
      paginator.value = { ...defaultPaginator }
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      loading.value = true
      const resp = await getWorkflowsWithPage({
        current_page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        search_word,
        status,
      })
      const data = resp.data

      paginator.value = data.paginator

      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }

      if (init) {
        workflows.value = data.list
      } else {
        workflows.value.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, workflows, paginator, loadWorkflows }
}

export const useCreateWorkflow = () => {
  const loading = ref(false)
  const router = useRouter()

  const handleCreateWorkflow = async (req: CreateWorkflowRequest) => {
    try {
      loading.value = true
      const resp = await createWorkflow(req)

      Message.success('创建工作流成功')
      await router.push({
        name: 'space-workflows-detail',
        params: {
          workflow_id: resp.data.id,
        },
      })
    } finally {
      loading.value = false
    }
  }
  return { loading, handleCreateWorkflow }
}

export const useUpdateWorkflow = () => {
  const loading = ref(false)

  const handleUpdateWorkflow = async (workflow_id: string, req: UpdateWorkflowRequest) => {
    try {
      loading.value = true
      const resp = await updateWorkflow(workflow_id, req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateWorkflow }
}

export const useGetWorkflow = () => {
  const loading = ref(false)
  const workflow = ref<Partial<GetWorkflowResponse['data']>>({})

  const loadWorkflow = async (workflow_id: string) => {
    try {
// 调用API接口获取工作流基础信息
      loading.value = true
      const resp = await getWorkflow(workflow_id)
      workflow.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, workflow, loadWorkflow }
}

export const useDeleteWorkflow = () => {
  const handleDeleteWorkflow = (workflow_id: string, callback?: () => void) => {
    Modal.warning({
      title: '要删除该工作流吗？',
      content:
        '删除工作流后，发布的WebApp、开放API以及关联的社交媒体平台均无法使用该工作流，如果需要暂停工作流，可使禁用功能',
      hideCancel: false,
      onOk: async () => {
        try {
// 点击确定后向API接口发起请求
          const resp = await deleteWorkflow(workflow_id)
          Message.success(resp.message)
        } finally {
// 调用callback函数指定回调功能
          callback?.()
        }
      },
    })
  }
  return { handleDeleteWorkflow }
}

export const useGetDraftGraph = () => {
  const loading = ref(false)
  const nodes = ref<Node[]>([])
  const edges = ref<Edge[]>([])

  const loadDraftGraph = async (workFlow_id: string) => {
    try {
      loading.value = true
      const resp = await getDraftGraph(workFlow_id)

      const data = resp.data

      nodes.value = data.nodes.map((node: DraftGraphNode) => {
// 删除不传递的数据并构建新节点数据存储到data中
        const { id, node_type: type, position, ...rest } = node
        return { id, type, position, data: rest } as Node
      })

      edges.value = data.edges.map((edge: DraftGraphEdge) => {
// 添加动画，并设置边的粗细+颜色
        const { id, source, target, ...rest } = edge
        return {
          id,
          source,
          target,
          ...rest,
          animated: true,
          style: { strokeWidth: 2, stroke: '#9ca3af' },
        } as Edge
      })
    } finally {
      loading.value = false
    }
  }

  return { loading, nodes, edges, loadDraftGraph }
}

export const useUpdateDraftGraph = () => {
  const loading = ref(false)

  const handleUpdateDraftGraph = async (
    workflow_id: string,
    req: UpdateDraftGraphRequest,
    is_notify: boolean = true,
  ) => {
    try {
// 调用api接口更新草稿图配置
      loading.value = true
      const resp = await updateDraftGraph(workflow_id, req)
      if (is_notify) {
        Message.success(resp.message)
      }
    } finally {
      loading.value = false
    }
  }

// 定义图配置数据转请求数据函数
  const convertGraphToReq = (
    nodes: Node[],
    edges: Edge[],
  ): UpdateDraftGraphRequest => {
    return {
      nodes: nodes.map((node) => {
        return {
          id: node.id,
          node_type: node.type ?? '',
          position: node.position,
          ...node.data,
        }
      }),
      edges: edges.map((edge) => {
        const edgeWithMeta = edge as Edge & { source_type?: string; target_type?: string }
        return {
          id: edge.id,
          source: edge.source,
          source_type: edgeWithMeta.source_type,
          target: edge.target,
          target_type: edgeWithMeta.target_type,
        }
      }),
    }
  }

  return { loading, convertGraphToReq, handleUpdateDraftGraph }
}

export const usePublishWorkflow = () => {
  const loading = ref(false)

  const handlePublishWorkflow = async (workflow_id: string) => {
    try {
      loading.value = true
      const resp = await publishWorkflow(workflow_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handlePublishWorkflow }
}

export const useCancelPublishWorkflow = () => {
  const loading = ref(false)

  const handleCancelPublish = async (workflow_id: string) => {
    try {
      loading.value = true
      const resp = await cancelPublishWorkflow(workflow_id)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleCancelPublish }
}

export const useDebugWorkflow = () => {
  const loading = ref(false)
  const error = ref('')

  const handleDebugWorkflow = async (
    workflow_id: string,
    inputs: Record<string, unknown>,
    onData: (event_response: Record<string, unknown>) => void,
    onError?: (event_response: Record<string, unknown>) => void,
    opts?: { node_ids?: string[] },
  ) => {
    try {
      loading.value = true
      const resp = await debugWorkflow(workflow_id, inputs, onData, onError, opts)
// 判断响应内容是否存在，如果存在则表示该接口为非流式输出，意味着接口出错
      if (resp) {
        error.value = resp.message ?? resp.msg ?? '未知错误'
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, error, handleDebugWorkflow }
}
