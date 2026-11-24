<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import LlmProviderConfig from './components/LlmProviderConfig.vue'
import CustomLlmModelConfig from './components/CustomLlmModelConfig.vue'
import OssProviderConfig from './components/OssProviderConfig.vue'
import DatabaseConfig from './components/DatabaseConfig.vue'
import RedisConfig from './components/RedisConfig.vue'
import VectorDbConfig from './components/VectorDbConfig.vue'
import ThirdPartyConfig from './components/ThirdPartyConfig.vue'
import FeishuConfig from './components/FeishuConfig.vue'
import MemoryConfig from './components/MemoryConfig.vue'
import { getSystemConfig, saveSystemConfig } from '@/services/system-config.ts'

// tab 记忆：留在 /settings 路由内一直有效（含刷新，刷新不跳回第一个）；
// 点击左侧菜单离开该路由时清除 —— 下次进入默认回到第一个 tab（llm）。
const SETTINGS_TAB_KEYS = ['llm', 'oss', 'database', 'redis', 'third', 'feishu', 'memory']
const ACTIVE_TAB_STORAGE_KEY = 'llmops-settings-active-tab'
const lastTab = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY)
const activeTab = ref<string>(
  lastTab && SETTINGS_TAB_KEYS.includes(lastTab) ? lastTab : 'llm',
)
watch(activeTab, (v) => localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, v))
onBeforeRouteLeave(() => {
  localStorage.removeItem(ACTIVE_TAB_STORAGE_KEY)
})

const envConfig = reactive<Record<string, string>>({
  // LLM
  OPENAI_API_KEY: '',
  OPENAI_API_BASE: 'https://api.openai.com/v1',
  DEEPSEEK_API_KEY: '',
  DEEPSEEK_API_BASE: 'https://api.deepseek.com/v1',
  MOONSHOT_API_KEY: '',
  MOONSHOT_API_BASE: 'https://api.moonshot.cn/v1',
  DASHSCOPE_API_KEY: '',
  DASHSCOPE_API_BASE: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  DASHSCOPE_BASE_HTTP_API_URL: '',
  LOCAL_LLM_API_KEY: '',
  LOCAL_LLM_API_BASE: 'http://127.0.0.1:1234/v1',
  LOCAL_LLM_MODEL: '',
  QWEN3_5_PLUS_API_KEY: '',
  QWEN3_5_PLUS_API_BASE: '',
  BROWSER_LLM_MODEL: 'qwen-vl-max',
  BROWSER_LLM_BASE_URL: '',
  BROWSER_HEADLESS: 'false',
  HUGGINGFACEHUB_API_TOKEN: '',
  HF_HUB_OFFLINE: '1',
  TRANSFORMERS_OFFLINE: '1',
  HF_ENDPOINT: 'https://hf-mirror.com',
  LANGSMITH_TRACING: 'true',
  LANGSMITH_ENDPOINT: 'https://api.smith.langchain.com',
  LANGSMITH_API_KEY: '',
  LANGSMITH_PROJECT: 'llmops',
  SERPER_API_KEY: '',
  GAODE_API_KEY: '',
  GAODE_API_DOMAIN: '',
  // Embedding / Rerank / OCR
  EMBEDDING_PROVIDER: 'local',
  EMBEDDING_MODEL: 'BAAI/bge-small-zh',
  EMBEDDING_DEVICE: 'cpu',
  EMBEDDING_API_KEY: '',
  EMBEDDING_API_BASE: '',
  RERANK_PROVIDER: 'local',
  RERANK_MODEL: 'BAAI/bge-reranker-v2-m3',
  RERANK_DEVICE: 'cpu',
  RERANK_API_KEY: '',
  RERANK_API_BASE: '',
  OCR_PROVIDER: 'api',
  OCR_API_MODEL: 'qwen-vl-ocr',
  OCR_API_KEY: '',
  OCR_API_BASE: '',
  QUERY_REWRITE_MODEL: 'deepseek-v4-flash',
  RETRIEVAL_EVAL_MODEL: 'deepseek-v4-flash',
  // OSS
  STORAGE_PROVIDER: '',
  MINIO_API_URL: '',
  MINIO_TIMEOUT: '60',
  COS_BASE_URL: '',
  COS_SECRET_ID: '',
  COS_SECRET_KEY: '',
  COS_REGION: 'ap-guangzhou',
  COS_BUCKET: '',
  COS_SCHEME: 'https',
  COS_DOMAIN: '',
  // 数据库
  SQLALCHEMY_DATABASE_URI: '',
  SQLALCHEMY_POOL_SIZE: '30',
  SQLALCHEMY_POOL_RECYCLE: '3600',
  SQLALCHEMY_ECHO: 'True',
  // Redis & Celery
  REDIS_HOST: '',
  REDIS_PORT: '6379',
  REDIS_USERNAME: '',
  REDIS_PASSWORD: '',
  REDIS_DB: '0',
  REDIS_USE_SSL: 'False',
  REDIS_SOCKET_TIMEOUT: '5',
  REDIS_CONNECT_TIMEOUT: '5',
  CELERY_BROKER_DB: '1',
  CELERY_RESULT_BACKEND_DB: '1',
  CELERY_TASK_IGNORE_RESULT: 'False',
  CELERY_RESULT_EXPIRES: '3600',
  CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP: 'True',
  // Weaviate
  WEAVIATE_HOST: '',
  WEAVIATE_PORT: '8080',
  WEAVIATE_GRPC_HOST: '',
  WEAVIATE_GRPC_PORT: '50051',
  WEAVIATE_API_KEY: '',
  // 第三方
  JWT_SECRET_KEY: '',
  GITHUB_CLIENT_ID: '',
  GITHUB_CLIENT_SECRET: '',
  GITHUB_CLIENT_REDIRECT_URI: 'http://localhost:5173/auth/authorize/github',
  GITHUB_OAUTH_BASE_URL: 'https://github.com',
  GITHUB_API_BASE_URL: 'https://api.github.com',
  ASSISTANT_AGENT_ID: '',
  // 飞书
  FEISHU_APP_ID: '',
  FEISHU_APP_SECRET: '',
  FEISHU_OPEN_API_BASE: 'https://open.feishu.cn/open-apis',
  LLMOPS_BASE_URL: '',
  LLMOPS_APP_ID: '',
  LLMOPS_ACCESS_TOKEN: '',
  // 记忆系统
  MEMORY_PROVIDER: 'builtin',
  TENCENT_MEMORY_ENDPOINT: '',
  TENCENT_MEMORY_API_KEY: '',
  TENCENT_MEMORY_SERVICE_ID: '',
  TENCENT_MEMORY_TEAM_ID: '',
  TENCENT_MEMORY_AGENT_ID: '',
  TENCENT_MEMORY_USER_ID: '',
  TENCENT_MEMORY_ADMIN_KEY: '',
})

const saving = ref(false)
const loading = ref(false)
// 敏感项（后端脱敏返回 '********'）：已有配置时前端显示已配置，不覆盖
const SENSITIVE = new Set([
  'JWT_SECRET_KEY', 'WEAVIATE_API_KEY', 'REDIS_PASSWORD', 'SQLALCHEMY_DATABASE_URI',
  'COS_SECRET_ID', 'COS_SECRET_KEY', 'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET',
  'OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'DASHSCOPE_API_KEY',
  'QWEN3_API_KEY', 'QWEN3_5_PLUS_API_KEY', 'LOCAL_LLM_API_KEY',
  'EMBEDDING_API_KEY', 'RERANK_API_KEY', 'OCR_API_KEY',
  'LANGSMITH_API_KEY', 'GAODE_API_KEY', 'SERPER_API_KEY', 'HUGGINGFACEHUB_API_TOKEN',
  'FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'LLMOPS_ACCESS_TOKEN',
  'TENCENT_MEMORY_API_KEY', 'TENCENT_MEMORY_ADMIN_KEY',
])

// 加载已保存配置回显（敏感项显示 '********' 占位，避免明文回显）
const loadConfig = async () => {
  loading.value = true
  try {
    const resp = await getSystemConfig()
    const saved = resp.data || {}
    for (const key of Object.keys(envConfig)) {
      if (key in saved && saved[key]) {
        envConfig[key] = saved[key]
      }
    }
  } catch (err) {
    Message.error('读取配置失败: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    // 过滤：敏感项已掩码（********）时不提交（保持原配置）；空值提交清空
    const configs: Record<string, string> = {}
    for (const [key, value] of Object.entries(envConfig)) {
      if (SENSITIVE.has(key) && value === '********') continue
      configs[key] = value
    }
    await saveSystemConfig(configs)
    Message.success('配置已保存（敏感项已加密入库，重启后生效）')
    await loadConfig()
  } catch (err) {
    Message.error('保存失败: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    saving.value = false
  }
}

onMounted(() => loadConfig())

const tabs = [
  { key: 'llm', label: '大模型配置' },
  { key: 'oss', label: '对象存储' },
  { key: 'database', label: '数据库' },
  { key: 'redis', label: 'Redis & Celery' },
  { key: 'third', label: '第三方集成' },
  { key: 'feishu', label: '飞书机器人' },
  { key: 'memory', label: '记忆系统' },
]
</script>

<template>
  <div class="flex-1 w-full min-h-0 h-full bg-white flex flex-col overflow-hidden">
    <div class="mx-6 mt-4 border border-gray-200 rounded-lg bg-white shrink-0 overflow-hidden">
      <div class="flex items-center justify-between h-14 px-4 border-b border-gray-100">
        <div>
          <span class="text-sm font-medium text-gray-700">系统设置</span>
          <span class="text-xs text-gray-400 ml-3"
            >修改后点击保存，配置将写入 .env 文件并在下次启动时生效</span
          >
        </div>
        <a-button type="primary" size="small" :loading="saving" @click="handleSave"
          >保存配置</a-button
        >
      </div>
      <!-- 菜单 tab（视口缩小时字号/间隙缩小，允许换行） -->
      <div class="flex items-center flex-wrap gap-6 max-md:gap-3 px-4 bg-white">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="py-2.5 text-sm max-md:text-[12px] transition-colors relative"
          :class="
            activeTab === tab.key
              ? 'text-blue-600 font-medium'
              : 'text-gray-500 hover:text-gray-700'
          "
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
          <span
            v-if="activeTab === tab.key"
            class="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-t"
          />
        </button>
      </div>
    </div>
    <!-- 内容区 -->
    <div class="flex-1 overflow-y-auto px-6 pt-4 no-scrollbar">
      <llm-provider-config v-if="activeTab === 'llm'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <custom-llm-model-config v-if="activeTab === 'llm'" />
      <oss-provider-config v-if="activeTab === 'oss'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <database-config v-if="activeTab === 'database'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <vector-db-config v-if="activeTab === 'database'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <redis-config v-if="activeTab === 'redis'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <third-party-config v-if="activeTab === 'third'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <feishu-config v-if="activeTab === 'feishu'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
      <memory-config v-if="activeTab === 'memory'" :model-value="envConfig" @update:model-value="Object.assign(envConfig, $event)" />
    </div>
  </div>
</template>

<style scoped>
/* 针对 Webkit 浏览器 (Chrome, Safari, Edge) */
.no-scrollbar::-webkit-scrollbar {
  display: none;
}

/* 针对 Firefox 和 IE/Edge (旧版) */
.no-scrollbar {
  -ms-overflow-style: none; /* IE and Edge */
  scrollbar-width: none; /* Firefox */
}
</style>
