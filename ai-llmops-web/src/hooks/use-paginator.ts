import { reactive } from 'vue'

export interface PaginationState {
  current: number
  pageSize: number
  total: number
  showTotal: boolean
  showJumper?: boolean
  showPageSize?: boolean
}

// 后端分页响应中的 paginator 字段
export interface PaginatorData {
  current_page: number
  page_size: number
  total_page: number
  total_record: number
}

export const usePagination = (defaultPageSize = 1) => {
  const pagination = reactive<PaginationState>({
    current: 1,
    pageSize: defaultPageSize,
    total: 0,
    showTotal: true,
    showJumper: true,
    showPageSize: true,
  })

  // 重置分页
  const resetPagination = () => {
    pagination.current = 1
  }

  // 更新分页
  const updatePagination = (paginatorData: PaginatorData) => {
    pagination.current = Number(paginatorData.current_page)
    pagination.pageSize = Number(paginatorData.page_size)
    pagination.total = Number(paginatorData.total_record)
  }

  return {
    pagination,
    resetPagination,
    updatePagination,
  }
}
