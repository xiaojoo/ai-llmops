export type BaseResponse<T> = {
  code: string
  message: string
  data: T
}

// 基础分页数据结构
export type BasePaginatorRequest = {
  current_page: number
  page_size: number
}

export type BasePaginatorResponse<T> = BaseResponse<{
  list: Array<T>
  paginator: {
    total_page: number
    total_record: number
    current_page: number
    page_size: number
  }
}>

// 获取应用的调试会话消息列表请求结构
export type GetDebugConversationMessagesWithPageRequest = BasePaginatorRequest & {
  created_at?: number
}
