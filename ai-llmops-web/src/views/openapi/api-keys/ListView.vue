<script setup lang="ts">
import moment from 'moment'
import { onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  useDeleteApiKey,
  useGetApiKeysWithPage,
  useUpdateApiKeyIsActive,
} from '@/hooks/use-api-key.ts'
import { useRoute, useRouter } from 'vue-router'
import CreateOrUpdateApiKeyModal from '@/views/openapi/api-keys/components/CreateOrUpdateApiKeyModal.vue'

const route = useRoute()
const router = useRouter()

const { handleUpdateApiKeyIsActive } = useUpdateApiKeyIsActive()
const {
  loading: getApiKeysWithPageLoading,
  api_keys,
  paginator,
  loadApiKeys,
} = useGetApiKeysWithPage()
const { handleDeleteApiKey } = useDeleteApiKey()

const createOrUpdateApiKeyModalVisible = ref(false)
const updateApiKeyId = ref('')
const updateApiKeyIsActive = ref(false)
const updateApiKeyRemark = ref('')

const props = defineProps({
  create_api_key: { type: Boolean, required: true, default: false },
})
const emits = defineEmits(['update:create_api_key'])

// 定义写入剪切板函数
const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    Message.success('复制成功')
  } catch (err) {
    Message.error(String(err))
  }
}

// 页面加载完毕后获取api秘钥列表数据
onMounted(() => {
  loadApiKeys(true)
})

// 监听create_api_key是否开启，执行创建操作
watch(
  () => props.create_api_key,
  (value) => {
    // 清空updateApiKeyId
    updateApiKeyId.value = ''

    // 显示or隐藏模态窗
    createOrUpdateApiKeyModalVisible.value = Boolean(value)
  },
)

// 监听路由query变化，重新加载数据
watch(
  () => route.query,
  async (newQuery, oldQuery) => {
    if (newQuery.current_page !== oldQuery.current_page) {
      await loadApiKeys()
    }
  },
)
</script>

<template>
  <!-- overflow-auto：只有内容真的超出才出现滚动条；无数据时空状态正常显示，不再出现常显的上下滚动条 -->
  <div class="h-[calc(100vh-160px)] overflow-auto scrollbar-w-none">
    <a-table
      hoverable
      :pagination="{
        total: paginator.total_record,
        current: paginator.current_page,
        defaultCurrent: 1,
        pageSize: paginator.page_size,
        defaultPageSize: 20,
        showTotal: true,
      }"
      :loading="getApiKeysWithPageLoading"
      :bordered="{ wrapper: false }"
      :scroll="{ x: 1240 }"
      :data="api_keys"
      @page-change="
        (page: number) => {
          router.push({
            path: route.path,
            query: { current_page: page },
          })
        }
      "
    >
      <template #columns>
        <a-table-column
          title="#"
          data-index="index"
          align="center"
          :width="80"
          fixed="left"
          header-cell-class="rounded-tl-lg !bg-gray-200 text-gray-700"
          cell-class="bg-white"
        >
          <template #cell="{ rowIndex }">
            {{ rowIndex + 1 }}
          </template>
        </a-table-column>
        <a-table-column
          title="秘钥"
          data-index="api_key"
          :width="400"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent text-gray-700"
        >
          <template #cell="{ record }">
            <div class="flex items-center min-w-0">
              <div class="line-clamp-1">{{ record.api_key }}</div>
              <a-button
                size="mini"
                class="flex-shrink-0 rounded ml-2"
                @click="async () => copyToClipboard(record.api_key)"
              >
                <template #icon>
                  <icon-copy />
                </template>
              </a-button>
            </div>
          </template>
        </a-table-column>
        <a-table-column
          title="状态"
          data-index="is_active"
          :width="80"
          header-cell-class="!bg-gray-200 text-gray-700 whitespace-nowrap"
          cell-class="bg-transparent text-gray-700 whitespace-nowrap"
        >
          <template #cell="{ record }">
            <a-space>
              <div
                v-if="record.is_active"
                class="w-2 h-2 bg-green-500 rounded-sm border border-green-700"
              ></div>
              <div v-else class="w-2 h-2 bg-gray-500 rounded-sm border border-gray-700"></div>
              <div v-if="record.is_active" class="text-gray-700">可用</div>
              <div v-else class="text-gray-700">已禁用</div>
            </a-space>
          </template>
        </a-table-column>
        <a-table-column
          title="创建时间"
          data-index="created_at"
          :width="180"
          header-cell-class="!bg-gray-200 text-gray-700 whitespace-nowrap"
          cell-class="bg-transparent text-gray-700 whitespace-nowrap"
        >
          <template #cell="{ record }">
            {{ moment(record.created_at * 1000).format('YYYY-MM-DD hh:mm:ss') }}
          </template>
        </a-table-column>
        <a-table-column
          title="备注"
          :width="400"
          data-index="remark"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent text-gray-700"
        >
          <template #cell="{ record }">
            <div class="line-clamp-1">{{ record.remark }}</div>
          </template>
        </a-table-column>
        <a-table-column
          title="操作"
          data-index="operator"
          header-cell-class="rounded-tr-lg !bg-gray-200 text-gray-700"
          cell-class="bg-white !h-[40px]"
          :width="100"
          fixed="right"
        >
          <template #cell="{ record }">
            <a-space :size="0">
              <template #split>
                <a-divider direction="vertical" />
              </template>
              <a-switch
                size="small"
                type="round"
                :model-value="record.is_active"
                @change="
                  (value) => {
                    handleUpdateApiKeyIsActive(record.id, value as boolean, () => {
                      // 更新对应记录的状态文字描述
                      record.is_active = Boolean(value)
                    })
                  }
                "
              />
              <a-dropdown position="br">
                <a-button aria-label="更多操作" type="text" size="mini" class="!text-gray-700">
                  <template #icon>
                    <icon-more />
                  </template>
                </a-button>
                <template #content>
                  <a-doption
                    @click="
                      () => {
                        updateApiKeyId = record.id
                        updateApiKeyIsActive = record.is_active
                        updateApiKeyRemark = record.remark
                        createOrUpdateApiKeyModalVisible = true
                      }
                    "
                  >
                    重命名
                  </a-doption>
                  <a-doption
                    class="!text-red-700"
                    @click="
                      () =>
                        handleDeleteApiKey(record.id, async () => {
                          await loadApiKeys()
                        })
                    "
                  >
                    删除
                  </a-doption>
                </template>
              </a-dropdown>
            </a-space>
          </template>
        </a-table-column>
      </template>
    </a-table>
    <!-- 新增or重命名模态窗 -->
    <create-or-update-api-key-modal
      v-model:visible="createOrUpdateApiKeyModalVisible"
      v-model:api_key_id="updateApiKeyId"
      v-model:is_active="updateApiKeyIsActive"
      v-model:remark="updateApiKeyRemark"
      @update:visible="(value) => emits('update:create_api_key', value)"
      :callback="async () => await loadApiKeys()"
    />
  </div>
</template>

<style scoped></style>
