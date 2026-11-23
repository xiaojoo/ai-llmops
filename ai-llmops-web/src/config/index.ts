// api请求接口前缀
// export const apiPrefix: string = 'http://localhost:5173/api'
export const apiPrefix: string = '/api'

// 业务状态码
export const httpCode = {
  success: 'success',
  fail: 'fail',
  notFound: 'not_found',
  unauthorized: 'unauthorized',
  forbidden: 'forbidden',
  validateError: 'validate_error',
}

export interface TypeMap {
  str: string
  int: string
  float: string
  bool: string
  [key: string]: string
}

// 类型字符串与中文映射
// 兼容两套类型名：yaml params 的简写（str/int/float/bool）与
// pydantic args_schema 的 JSON Schema 类型名（string/integer/boolean/number）
export const typeMap: TypeMap = {
  str: '字符串',
  int: '整形',
  float: '浮点型',
  bool: '布尔值',
  string: '字符串',
  integer: '整数',
  number: '数字',
  boolean: '布尔值',
}

// 智能体事件类型
export const QueueEvent = {
  longTermMemoryRecall: 'long_term_memory_recall',
  agentThought: 'agent_thought',
  agentMessage: 'agent_message',
  agentAction: 'agent_action',
  askUser: 'ask_user',
  datasetRetrieval: 'dataset_retrieval',
  agentEnd: 'agent_end',
  subTaskPlan: 'sub_task_plan',
  subTaskStart: 'sub_task_start',
  subTaskEnd: 'sub_task_end',
  stop: 'stop',
  error: 'error',
  timeout: 'timeout',
  ping: 'ping',
}
