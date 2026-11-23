import { http } from '@/utils/http'
import type {
  CreateDatasetRequest,
  CreateDocumentsRequest,
  CreateDocumentsResponse,
  CreateSegmentRequest,
  GetDatasetQueriesResponse,
  GetDatasetResponse,
  GetDatasetsWithPageResponse,
  GetDocumentResponse,
  GetDocumentsStatusResponse,
  GetDocumentsWithPageRequest,
  GetDocumentsWithPageResponse,
  GetSegmentResponse,
  GetSegmentsWithPageRequest,
  GetSegmentsWithPageResponse,
  HitRequest,
  HitResponse,
  PreviewChunk,
  UpdateDatasetRequest,
  UpdateSegmentRequest,
} from '@/models/dataset.ts'
import type { BaseResponse } from '@/models/base.ts'

enum API {
  DATASETS_BASE = '/datasets',
}

// 获取知识库分页列表
export const getDatasetsWithPage = (
  current_page: number = 1,
  page_size: number = 20,
  search_word: string = '',
) =>
  http.get<GetDatasetsWithPageResponse>(API.DATASETS_BASE, {
    current_page,
    page_size,
    search_word,
  })

// 创建知识库
export const createDataset = (req: CreateDatasetRequest) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE, req)

// 更新知识库
export const updateDataset = (dataset_id: string, req: UpdateDatasetRequest) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}`, req)

// 删除知识库
export const deleteDataset = (dataset_id: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/delete`)

// 获取知识库详情
export const getDataset = (dataset_id: string) =>
  http.get<GetDatasetResponse>(API.DATASETS_BASE + `/${dataset_id}`)

// 获取文档分页列表
export const getDocumentsWithPage = (
  dataset_id: string,
  req: GetDocumentsWithPageRequest = {
    current_page: 1,
    page_size: 20,
    search_word: '',
  },
) => http.get<GetDocumentsWithPageResponse>(API.DATASETS_BASE + `/${dataset_id}/documents`, req)

// 获取指定文档详情
export const getDocument = (dataset_id: string, document_id: string) =>
  http.get<GetDocumentResponse>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}`)

// 更改指定文档状态
export const updateDocumentEnable = (dataset_id: string, document_id: string, enabled: boolean) =>
  http.post<BaseResponse<unknown>>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/enabled`,
    {
      enabled,
    },
  )

// 删除指定文档详情
export const deleteDocument = (dataset_id: string, document_id: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/delete`)

// 重试构建文档索引（用于异步处理失败的文档）
export const retryDocument = (dataset_id: string, document_id: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/retry`)

// 暂停文档构建（等待/失败状态的任务可暂停）
export const pauseDocument = (dataset_id: string, document_id: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/pause`)

// 继续文档构建（暂停状态的任务可继续）
export const resumeDocument = (dataset_id: string, document_id: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/resume`)

// 更改指定文档名字
export const updateDocumentName = (dataset_id: string, document_id: string, name: string) =>
  http.post<BaseResponse<unknown>>(API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/name`, {
    name,
  })

// 知识库召回测试
export const hit = (dataset_id: string, req: HitRequest) =>
  http.post<HitResponse>(API.DATASETS_BASE + `/${dataset_id}/hit`, req)

// 创建知识库
export const createDocuments = (dataset_id: string, req: CreateDocumentsRequest) =>
  http.post<CreateDocumentsResponse>(API.DATASETS_BASE + `/${dataset_id}/documents`, req)

// 切片预览：按当前分段方式/规则切分第一个文件，返回前几块
export const previewChunks = (dataset_id: string, req: CreateDocumentsRequest) =>
  http.post<BaseResponse<PreviewChunk[]>>(API.DATASETS_BASE + `/${dataset_id}/documents/preview-chunks`, req)

// 最近查询记录
export const getDatasetQueries = (dataset_id: string) =>
  http.get<GetDatasetQueriesResponse>(API.DATASETS_BASE + `/${dataset_id}/queries`)

// 根据批处理标识获取文档的处理状态
export const getDocumentsStatus = (dataset_id: string, batch: string) =>
  http.get<GetDocumentsStatusResponse>(
    API.DATASETS_BASE + `/${dataset_id}/documents/batch/${batch}`,
  )

//获取指定文档片段列表
export const getSegmentsWithPage = (
  dataset_id: string,
  document_id: string,
  req: GetSegmentsWithPageRequest,
) =>
  http.get<GetSegmentsWithPageResponse>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments`,
    req,
  )

// 新增文档片段信息
export const createSegment = (dataset_id: string, document_id: string, req: CreateSegmentRequest) =>
  http.post<BaseResponse<unknown>>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments`,
    req,
  )

// 删除文档片段信息
export const deleteSegment = (dataset_id: string, document_id: string, segment_id: string) =>
  http.post<BaseResponse<unknown>>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments/${segment_id}/delete`,
  )

// 修改文档片段内容
export const updateSegment = (
  dataset_id: string,
  document_id: string,
  segment_id: string,
  req: UpdateSegmentRequest,
) =>
  http.post<BaseResponse<unknown>>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments/${segment_id}`,
    req,
  )

// 修改文档片段内容启用状态
export const updateSegmentEnabled = (
  dataset_id: string,
  document_id: string,
  segment_id: string,
  enabled: boolean,
) =>
  http.post<BaseResponse<unknown>>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments/${segment_id}/enabled`,
    { enabled },
  )

// 查询文档片段详情
export const getSegment = (dataset_id: string, document_id: string, segment_id: string) =>
  http.get<GetSegmentResponse>(
    API.DATASETS_BASE + `/${dataset_id}/documents/${document_id}/segments/${segment_id}`,
  )
