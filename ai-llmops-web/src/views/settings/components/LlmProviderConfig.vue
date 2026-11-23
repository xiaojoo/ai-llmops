<script setup lang="ts">
import ConfigGroup from './ConfigGroup.vue'
import ConfigRow from './ConfigRow.vue'

defineProps<{ modelValue: Record<string, string> }>()
defineEmits(['update:modelValue'])
</script>

<template>
  <div>
    <config-group title="OpenAI">
      <config-row label="API Key" env-key="OPENAI_API_KEY" :model-value="modelValue" sensitive placeholder="sk-..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="OPENAI_API_BASE" :model-value="modelValue" placeholder="https://api.openai.com/v1" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="DeepSeek">
      <config-row label="API Key" env-key="DEEPSEEK_API_KEY" :model-value="modelValue" sensitive placeholder="sk-..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="DEEPSEEK_API_BASE" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="Moonshot（月之暗面）">
      <config-row label="API Key" env-key="MOONSHOT_API_KEY" :model-value="modelValue" sensitive placeholder="sk-..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="MOONSHOT_API_BASE" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="通义千问（DashScope）">
      <config-row label="API Key" env-key="DASHSCOPE_API_KEY" :model-value="modelValue" sensitive placeholder="sk-..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="DASHSCOPE_API_BASE" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="语音服务 TTS/ASR 接口地址" env-key="DASHSCOPE_BASE_HTTP_API_URL" :model-value="modelValue" placeholder="留空使用默认 https://dashscope.aliyuncs.com/api/v1" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="本地离线模型（OpenAI 兼容端点）" subtitle="本地 vLLM / LM Studio 等端点，模型 ID 可自定义，不限定 Qwen">
      <config-row label="模型名称" env-key="LOCAL_LLM_MODEL" :model-value="modelValue" placeholder="qwen/qwen3.8-27b" hint="本地端点实际加载的模型 ID（更换本地模型时请同步修改）" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Key" env-key="LOCAL_LLM_API_KEY" :model-value="modelValue" sensitive placeholder="lm-studio" hint="本地端点通常不校验 Key，可留空" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="LOCAL_LLM_API_BASE" :model-value="modelValue" placeholder="http://127.0.0.1:1234/v1" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="千问多模态（qwen3_5-plus）" subtitle="DashScope OpenAI 兼容端点，未配置时回退 DASHSCOPE_API_BASE / DASHSCOPE_API_KEY">
      <config-row label="API Key" env-key="QWEN3_5_PLUS_API_KEY" :model-value="modelValue" sensitive placeholder="留空回退 DASHSCOPE_API_KEY" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Base URL" env-key="QWEN3_5_PLUS_API_BASE" :model-value="modelValue" placeholder="留空回退 DASHSCOPE_API_BASE" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="浏览器自动化 LLM" subtitle="浏览器自动化识别模型，必须用多模态视觉模型（DeepSeek 等纯文本模型不支持视觉）">
      <config-row label="LLM 模型" env-key="BROWSER_LLM_MODEL" :model-value="modelValue" placeholder="qwen-vl-max" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="LLM Base URL" env-key="BROWSER_LLM_BASE_URL" :model-value="modelValue" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="无头模式" env-key="BROWSER_HEADLESS" :model-value="modelValue" type="select" :options="[{label:'开启（生产环境）',value:'true'},{label:'关闭（本地调试）',value:'false'}]" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="Embedding 嵌入服务" subtitle="向量化服务（local | api），模型维度须与存量向量数据一致">
      <config-row label="提供者" env-key="EMBEDDING_PROVIDER" :model-value="modelValue" type="select" :options="[{label:'local（本地模型）',value:'local'},{label:'api（云端接口）',value:'api'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="模型" env-key="EMBEDDING_MODEL" :model-value="modelValue" placeholder="BAAI/bge-small-zh" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="推理设备" env-key="EMBEDDING_DEVICE" :model-value="modelValue" placeholder="cpu" hint="cpu | cuda | mps" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Key" env-key="EMBEDDING_API_KEY" :model-value="modelValue" sensitive placeholder="api 模式必填" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Base" env-key="EMBEDDING_API_BASE" :model-value="modelValue" placeholder="api 模式填写" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="Rerank 精排服务" subtitle="检索结果精排（local | api），api 模式需配置云端 Key">
      <config-row label="提供者" env-key="RERANK_PROVIDER" :model-value="modelValue" type="select" :options="[{label:'local（本地模型）',value:'local'},{label:'api（云端接口）',value:'api'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="模型" env-key="RERANK_MODEL" :model-value="modelValue" placeholder="BAAI/bge-reranker-v2-m3" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="推理设备" env-key="RERANK_DEVICE" :model-value="modelValue" placeholder="cpu" hint="cpu | cuda | mps" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Key" env-key="RERANK_API_KEY" :model-value="modelValue" sensitive placeholder="api 模式必填" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Base" env-key="RERANK_API_BASE" :model-value="modelValue" placeholder="api 模式填写" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="OCR 文字识别" subtitle="文档图片文字识别（local | api | custom）">
      <config-row label="提供者" env-key="OCR_PROVIDER" :model-value="modelValue" type="select" :options="[{label:'api（DashScope qwen-vl-ocr）',value:'api'},{label:'local（RapidOCR 本地）',value:'local'},{label:'custom（自定义接口）',value:'custom'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API 模型" env-key="OCR_API_MODEL" :model-value="modelValue" placeholder="qwen-vl-ocr" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Key" env-key="OCR_API_KEY" :model-value="modelValue" sensitive placeholder="留空默认使用 DASHSCOPE_API_KEY" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="API Base" env-key="OCR_API_BASE" :model-value="modelValue" placeholder="留空默认使用 DASHSCOPE_API_BASE" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="检索与查询改写" subtitle="RAG 链路中的模型选择，默认使用 DeepSeek">
      <config-row label="查询改写模型" env-key="QUERY_REWRITE_MODEL" :model-value="modelValue" placeholder="deepseek-v4-flash" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="检索评估模型" env-key="RETRIEVAL_EVAL_MODEL" :model-value="modelValue" placeholder="deepseek-v4-flash" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="Hugging Face">
      <config-row label="API Token" env-key="HUGGINGFACEHUB_API_TOKEN" :model-value="modelValue" sensitive placeholder="hf_..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="离线模式" env-key="HF_HUB_OFFLINE" :model-value="modelValue" type="select" :options="[{label:'开启',value:'1'},{label:'关闭',value:'0'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Transformers 离线" env-key="TRANSFORMERS_OFFLINE" :model-value="modelValue" type="select" :options="[{label:'开启',value:'1'},{label:'关闭',value:'0'}]" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="镜像地址" env-key="HF_ENDPOINT" :model-value="modelValue" placeholder="https://hf-mirror.com" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="LangSmith（链路追踪）">
      <config-row label="API Key" env-key="LANGSMITH_API_KEY" :model-value="modelValue" sensitive placeholder="lsv2_..." @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Endpoint" env-key="LANGSMITH_ENDPOINT" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="Project" env-key="LANGSMITH_PROJECT" :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="开启追踪" env-key="LANGSMITH_TRACING" :model-value="modelValue" type="select" :options="[{label:'开启',value:'true'},{label:'关闭',value:'false'}]" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>

    <config-group title="其他工具 API">
      <config-row label="Serper API Key" env-key="SERPER_API_KEY" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="高德地图 API Key" env-key="GAODE_API_KEY" :model-value="modelValue" sensitive @update:model-value="$emit('update:modelValue', $event)" />
      <config-row label="高德地图接口域名" env-key="GAODE_API_DOMAIN" :model-value="modelValue" placeholder="https://restapi.amap.com/v3" @update:model-value="$emit('update:modelValue', $event)" />
    </config-group>
  </div>
</template>
