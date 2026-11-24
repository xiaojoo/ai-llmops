<script setup lang="ts">
import { nextTick, type PropType, reactive, ref, watch } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'
import cloneDeep from 'lodash/cloneDeep'
import { getSkillListWithPage } from '@/services/skill.ts'
import type { GetSkillListWithPageResponse } from '@/models/skill.ts'

interface SkillItem {
  id: string
  name: string
  icon: string
  description: string
}

const props = defineProps({
  app_id: { type: String, required: true },
  skills: {
    type: Array as PropType<SkillItem[]>,
    required: true,
    default: () => [],
  },
})

const emits = defineEmits(['update:skills'])

const { loading: updateDraftAppConfigLoading, handleUpdateDraftAppConfig } =
  useUpdateDraftAppConfig()

// ─── 分页 ────────────────────────────────────────────────────
const loading = ref(false)
const paginator = reactive({
  current_page: 1,
  page_size: 20,
  total_page: 0,
  total_record: 0,
})
const apiSkills = ref<GetSkillListWithPageResponse['data']['list']>([])

const loadSkills = async (init = false) => {
  if (!init && paginator.current_page > paginator.total_page) return
  try {
    loading.value = true
    const resp = await getSkillListWithPage({
      current_page: paginator.current_page,
      page_size: paginator.page_size,
    })
    const data = resp.data
    paginator.current_page = data.paginator.current_page
    paginator.page_size = data.paginator.page_size
    paginator.total_page = data.paginator.total_page
    paginator.total_record = data.paginator.total_record
    if (paginator.current_page <= paginator.total_page) {
      paginator.current_page += 1
    }
    if (init) {
      apiSkills.value.splice(0, apiSkills.value.length, ...data.list)
    } else {
      apiSkills.value.push(...data.list)
    }
  } finally {
    loading.value = false
  }
}

// ─── 弹窗状态 ────────────────────────────────────────────────
const skillsModalVisible = ref(false)
const activateSkills = ref<SkillItem[]>([])
const originSkills = ref<SkillItem[]>([])

const handleScroll = async (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) return
    await loadSkills()
  }
}

const handleCancelSkillsModal = () => {
  skillsModalVisible.value = false
  activateSkills.value = cloneDeep(originSkills.value)
}

const handleSelectSkill = (idx: number) => {
  const skill = apiSkills.value[idx]
  if (!skill) return
  if (activateSkills.value.some((s) => s.id === skill.id)) {
    activateSkills.value = activateSkills.value.filter((s) => s.id !== skill.id)
  } else {
    if (activateSkills.value.length >= 12) {
      Message.warning('关联技能已超过12个，无法继续关联')
      return
    }
    activateSkills.value.push({
      id: skill.id,
      name: skill.name,
      icon: skill.icon,
      description: skill.description,
    })
  }
}

const handleSubmitSkills = async () => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, {
      skills: activateSkills.value.map((s) => s.id),
    })
    originSkills.value = cloneDeep(activateSkills.value)
    await nextTick()
    emits('update:skills', cloneDeep(activateSkills.value))
    handleCancelSkillsModal()
  } catch (e) {
    showErrorToast(String(e))
  }
}

const handleRemoveSkill = async (idx: number) => {
  const newSkills = [...props.skills]
  newSkills.splice(idx, 1)
  await handleUpdateDraftAppConfig(props.app_id, {
    skills: newSkills.map((s) => s.id),
  })
  activateSkills.value = cloneDeep(newSkills)
  originSkills.value = cloneDeep(newSkills)
  emits('update:skills', newSkills)
}

// ─── watch ───────────────────────────────────────────────────
watch(
  () => props.skills,
  (newValue) => {
    const list = Array.isArray(newValue) ? newValue : []
    const initData = list.map((s) => ({
      id: s.id,
      name: s.name,
      icon: s.icon,
      description: s.description,
    }))
    activateSkills.value = cloneDeep(initData)
    originSkills.value = cloneDeep(initData)
  },
  { immediate: true, deep: true },
)

watch(
  () => skillsModalVisible.value,
  async (newValue) => {
    if (newValue) {
      paginator.current_page = 1
      paginator.total_page = 0
      await loadSkills(true)
    } else {
      apiSkills.value.splice(0, apiSkills.value.length)
    }
  },
)
// 供外部（左侧「Skills」导航）直接打开选择技能弹窗
defineExpose({ openAdd: () => { skillsModalVisible.value = true } })
</script>

<template>
  <div>
    <a-collapse-item key="skills" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">Skills</div>
      </template>
      <template #extra>
        <a-space>
          <a-button aria-label="添加"
            size="mini"
            type="text"
            class="!text-gray-700"
            @click.stop="skillsModalVisible = true"
          >
            <template #icon><icon-plus /></template>
          </a-button>
        </a-space>
      </template>

      <div v-if="props.skills?.length > 0" class="flex flex-col gap-1">
        <div
          v-for="(skill, idx) in props.skills"
          :key="skill.id"
          class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
        >
          <div class="flex items-center gap-2">
            <a-avatar
              :size="36"
              shape="square"
              class="rounded shrink-0 bg-blue-600"
              :image-url="skill.icon"
            >
              <icon-code v-if="!skill.icon" />
            </a-avatar>
            <div class="flex flex-col flex-1 gap-1 h-9">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1">
                {{ skill.name }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1">{{ skill.description }}</div>
            </div>
          </div>
          <a-button aria-label="删除"
            size="mini"
            type="text"
            class="hidden group-hover:block shrink-0 ml-2 !text-red-700 rounded"
            @click="handleRemoveSkill(idx)"
          >
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>

      <div v-else class="text-xs text-gray-500 leading-[28px]">
        技能支持为 AI 应用扩展特定能力，例如 GIF 创建、数据分析等，应用最多支持关联 12 个技能。
      </div>
    </a-collapse-item>

    <a-modal
      :visible="skillsModalVisible"
      hide-title
      :footer="false"
      width="max(340px, min(400px, calc(100vw - 32px)))"
      class="skills-modal"
      modal-class="h-[calc(100vh-32px)] right-4"
      @cancel="handleCancelSkillsModal"
    >
      <div class="flex items-center justify-between mb-6">
        <div class="text-lg font-bold text-gray-700">选择关联技能</div>
        <a-button aria-label="关闭" type="text" class="text-gray-700" size="small" @click="handleCancelSkillsModal">
          <template #icon><icon-close /></template>
        </a-button>
      </div>

      <div class="h-[calc(100vh-180px)] mb-4 overflow-scroll scrollbar-w-none">
        <a-spin
          :loading="loading"
          class="block h-full w-full scrollbar-w-none overflow-scroll"
          @scroll="handleScroll"
        >
          <div class="flex flex-col gap-2">
            <div
              v-for="(skill, idx) in apiSkills"
              :key="skill.id"
              :class="[
                'flex items-center gap-2 border px-3 py-2 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-700',
                activateSkills.some((s) => s.id === skill.id)
                  ? 'bg-blue-50 border-blue-700'
                  : 'border-gray-200',
              ]"
              @click="handleSelectSkill(idx)"
            >
              <a-avatar
                :size="24"
                shape="square"
                class="shrink-0 rounded bg-blue-600"
                :image-url="skill.icon"
              >
                <icon-code v-if="!skill.icon" />
              </a-avatar>
              <div class="flex flex-col flex-1 min-w-0">
                <div class="line-clamp-1 text-gray-700 text-sm font-medium">{{ skill.name }}</div>
                <div class="line-clamp-1 text-gray-400 text-xs">{{ skill.description }}</div>
              </div>
              <icon-check
                v-if="activateSkills.some((s) => s.id === skill.id)"
                class="text-blue-700 shrink-0"
              />
            </div>

            <a-empty
              v-if="apiSkills.length === 0"
              description="没有可用的技能"
              class="h-[400px] flex flex-col items-center justify-center"
            />
          </div>

          <a-row v-if="paginator.total_page >= 2">
            <a-col
              v-if="paginator.current_page <= paginator.total_page"
              :span="24"
              class="text-center!"
            >
              <a-space class="my-4">
                <a-spin />
                <div class="text-gray-400">加载中</div>
              </a-space>
            </a-col>
            <a-col v-else :span="24" class="text-center!">
              <div class="text-gray-400 my-4">数据已加载完成</div>
            </a-col>
          </a-row>
        </a-spin>
      </div>

      <div class="flex items-center justify-between">
        <div class="text-sm text-gray-500">{{ activateSkills.length }} 个技能被选中</div>
        <a-space :size="12">
          <a-button class="rounded-lg" @click="handleCancelSkillsModal">取消</a-button>
          <a-button
            :loading="updateDraftAppConfigLoading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitSkills"
          >
            保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<style>
.skills-modal {
  .arco-modal-wrapper {
    text-align: right;
  }
}
</style>
