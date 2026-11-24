<script setup lang="ts">
import moment from 'moment'
import { useDeleteDocument, useGetDataset, useUpdateDocumentEnable } from '@/hooks/use-dataset.ts'
import { useRoute } from 'vue-router'
import { useGetDocumentsWithPage } from '@/hooks/use-dataset-test.ts'
import UpdateDocumentNameModal from '@/views/space/datasets/documents/components/UpdateDocumentNameModal.vue'
import TaskStatusModal from '@/views/space/datasets/documents/components/TaskStatusModal.vue'
import { ref } from 'vue'
import HitTestingModal from '@/views/space/datasets/documents/components/HitTestingModal.vue'
import type { GetDocumentsWithPageResponse } from '@/models/dataset.ts'

type DocumentItem = GetDocumentsWithPageResponse['data']['list'][number]

const route = useRoute()
const { dataset } = useGetDataset(String(route.params?.dataset_id))
const {
  loading,
  documents,
  pagination,
  onPageChange,
  onPageSizeChange,
  handleSearch,
  loadDocuments,
} = useGetDocumentsWithPage(String(route.params?.dataset_id))
const { handleDelete } = useDeleteDocument()
const { handleUpdateEnable } = useUpdateDocumentEnable()
const hitModalVisible = ref(false)
const taskModalVisible = ref(false)

const updateDocumentNameModalVisible = ref(false)
const updateDocumentID = ref('')

// 简单的搜索转接
const onSearch = (val: string) => {
  handleSearch(val)
}

const onEnableChange = (record: DocumentItem, rowIndex: number, value: boolean) => {
  handleUpdateEnable(String(route.params?.dataset_id), record.id, value, () => {
    const doc = documents.value[rowIndex]
    if (doc) {
      doc.enabled = value
    }
  })
}

const onRename = (record: DocumentItem) => {
  updateDocumentNameModalVisible.value = true
  updateDocumentID.value = record.id
}

const onDelete = (record: DocumentItem) => {
  handleDelete(String(route.params?.dataset_id), record.id, () => {
    loadDocuments()
  })
}
</script>

<template>
  <div class="p-6">
    <!-- 顶部知识库详情 -->
    <div class="flex items-center w-full gap-2 mb-6">
      <!-- 左侧回退按钮 -->
      <router-link :to="{ name: 'space-datasets-list' }">
        <a-button aria-label="返回" size="mini" type="text" class="!text-gray-700">
          <template #icon>
            <icon-left />
          </template>
        </a-button>
      </router-link>
      <!-- 右侧知识库信息 -->
      <div class="flex items-center gap-3">
        <!-- 知识库图标 -->
        <a-avatar :size="40" shape="square" class="rounded-lg" :image-url="dataset.icon" />
        <!-- 知识库信息 -->
        <div class="flex flex-col justify-between h-[40]">
          <a-skeleton-line v-if="!dataset?.name" :widths="[100]" />
          <div v-else class="text-gray-700">知识库 / {{ dataset.name }}</div>
          <div v-if="!dataset?.name" class="flex items-center gap-2">
            <a-skeleton-line :widths="[60]" :line-height="18" />
            <a-skeleton-line :widths="[60]" :line-height="18" />
            <a-skeleton-line :widths="[60]" :line-height="18" />
          </div>
          <div v-else class="flex items-center gap-2">
            <a-tag size="small" class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
              >{{ dataset.document_count }} 文档</a-tag
            >
            <a-tag size="small" class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
              >{{ dataset.hit_count }} 命中</a-tag
            >
            <a-tag size="small" class="rounded h-[18px] leading-[18px] bg-gray-200 text-gray-500"
              >{{ dataset.related_app_count }} 关联应用</a-tag
            >
          </div>
        </div>
      </div>
    </div>
    <!-- 中间检索以及召回测试 -->
    <div class="flex items-center justify-between mb-6">
      <!-- 左侧搜索框 -->
      <div class="w-[200px] shrink-0">
        <a-input-search
          :default-value="route.query?.search_word || ''"
          placeholder="请输入关键词搜索文档"
          class="bg-white rounded-lg border-gray-200"
          @search="onSearch"
          allow-clear
        />
      </div>
      <!--右侧按钮 -->
      <a-space :size="12">
        <a-button class="rounded-lg" @click="hitModalVisible = true">召回测试</a-button>
        <a-button class="rounded-lg" @click="taskModalVisible = true">
          <template #icon><icon-file /></template>
          任务查看
        </a-button>
        <router-link
          :to="{
            name: 'space-datasets-documents-create',
            params: { dataset_id: String(route.params?.dataset_id) },
          }"
        >
          <a-button type="primary" class="rounded-lg">添加文件</a-button>
        </router-link>
      </a-space>
    </div>
    <!-- 底部表格 -->
    <div class="">
      <a-table
        hoverable
        :pagination="pagination"
        :loading="loading"
        :data="documents"
        :bordered="{ wrapper: false }"
        :scroll="{ x: 1100 }"
        @page-change="onPageChange"
        @page-size-change="onPageSizeChange"
      >
        <template #columns>
          <a-table-column
            title="#"
            data-index="position"
            align="center"
            :width="80"
            fixed="left"
            header-cell-class="rounded-tl-lg !bg-gray-200 text-gray-700"
            cell-class="bg-white"
          />
          <a-table-column
            title="文档名称"
            data-index="name"
            :width="200"
            header-cell-class="!bg-gray-200 text-gray-700"
            cell-class="bg-white"
          >
            <template #cell="{ record }">
              <div class="min-w-0">
                <!-- {{ record.name }} -->
                <router-link
                  :to="{
                    name: 'space-datasets-documents-segments',
                    params: {
                      dataset_id: record.dataset_id,
                      document_id: record.id,
                    },
                  }"
                  class="line-clamp-1 text-blue-600 hover:underline block"
                >
                  {{ record.name }}
                </router-link>
                <!-- 文档元数据：标题 / 页数 / 页脚（PDF、Word 等提取） -->
                <a-tooltip
                  v-if="record.title || record.page_count || record.footer"
                  :content="`标题：${record.title || '无'}\n页数：${record.page_count || '未知'}\n页脚：${record.footer || '无'}`"
                >
                  <div class="flex items-center gap-1 text-xs text-gray-400 line-clamp-1 mt-0.5 cursor-help">
                    <template v-if="record.title">
                      <icon-file />
                      <span class="line-clamp-1">{{ record.title }}</span>
                    </template>
                    <span v-if="record.page_count" class="shrink-0">{{ record.page_count }} 页</span>
                  </div>
                </a-tooltip>
              </div>
            </template>
          </a-table-column>
          <a-table-column
            title="字符数"
            data-index="character_count"
            header-cell-class="!bg-gray-200 text-gray-700"
            cell-class="bg-transparent"
          >
            <template #cell="{ record }">
              {{ (record.character_count / 1000).toFixed(1) }}K
            </template>
          </a-table-column>
          <a-table-column
            title="召回次数"
            data-index="hit_count"
            header-cell-class="!bg-gray-200 text-gray-700"
            cell-class="bg-transparent"
          />
          <a-table-column
            title="上传时间"
            data-index="created_at"
            header-cell-class="!bg-gray-200 text-gray-700"
            cell-class="bg-transparent"
          >
            <template #cell="{ record }">
              {{ moment(record.created_at * 1000).format('YYYY-MM-DD HH:mm:ss') }}
            </template>
          </a-table-column>
          <a-table-column
            title="状态"
            data-index="enabled"
            header-cell-class="!bg-gray-200 text-gray-700"
            cell-class="bg-transparent"
          >
            <template #cell="{ record }">
              <a-space>
                <div
                  v-if="record.enabled"
                  class="w-2 h-2 bg-green-500 rounded-sm border border-green-700"
                ></div>
                <div v-else class="w-2 h-2 bg-gray-500 rounded-sm border border-gray-700"></div>
                <div v-if="record.enabled" class="border-green-700">可用</div>
                <div v-else class="border-gray-700">已禁用</div>
              </a-space>
            </template>
          </a-table-column>
          <a-table-column
            title="操作"
            data-index="operator"
            :width="100"
            fixed="right"
            header-cell-class="rounded-tr-lg !bg-gray-200 text-gray-700"
            cell-class="bg-white"
          >
            <template #cell="{ record, rowIndex }">
              <a-space :size="0">
                <template #split>
                  <a-divider direction="vertical" />
                </template>
                <a-tooltip
                  v-if="record.status == 'error'"
                  :content="`错误信息：${record.error}`"
                  position="tr"
                >
                  <a-switch size="small" type="round" :default-checked="false" disabled />
                </a-tooltip>
                <a-switch
                  v-else
                  size="small"
                  type="round"
                  :model-value="record.enabled"
                  @change="(value) => onEnableChange(record, rowIndex, Boolean(value))"
                />
                <a-dropdown position="br">
                  <a-button aria-label="更多操作" type="text" size="mini" class="!text-gray-700">
                    <template #icon>
                      <icon-more />
                    </template>
                  </a-button>
                  <template #content>
                    <a-doption @click="() => onRename(record)">重命名</a-doption>
                    <a-doption class="!text-red-700" @click="() => onDelete(record)">
                      删除
                    </a-doption>
                  </template>
                </a-dropdown>
              </a-space>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </div>

    <!-- 更改文档名字模态窗 -->
    <update-document-name-modal
      :document_id="updateDocumentID"
      :dataset_id="String(route.params?.dataset_id)"
      v-model:visible="updateDocumentNameModalVisible"
      :on-after-update="() => loadDocuments()"
    />

    <!-- 召回测试模态窗 -->
    <hit-testing-modal
      v-model:visible="hitModalVisible"
      :dataset_id="String(route.params?.dataset_id)"
    />

    <!-- 任务查看模态窗 -->
    <task-status-modal
      v-model:visible="taskModalVisible"
      :dataset_id="String(route.params?.dataset_id)"
      @update:visible="(v: boolean) => { taskModalVisible = v; if (!v) loadDocuments() }"
    />
  </div>
</template>

<style scoped></style>
