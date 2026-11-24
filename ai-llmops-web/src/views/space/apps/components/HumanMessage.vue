<script setup lang="ts">
const props = defineProps({
  account: { type: Object, required: true, default: () => ({}) },
  query: { type: String, required: true, default: '' },
})
</script>

<template>
  <!-- 人类消息 -->
  <div class="flex gap-2 flex-row-reverse">
    <!-- 头像 -->
    <a-avatar :size="30" shape="circle" class="shrink-0" :image-url="props.account?.avatar" />
    <!-- 右侧昵称与消息 -->
    <div class="flex flex-col items-end gap-2">
      <!-- 账号昵称 -->
      <div class="text-gray-700 font-bold">{{ props.account?.name }}</div>
      <!-- 人类消息 -->
      <div class="bg-blue-100 border border-blue-200 text-gray-700 px-4 py-3 rounded-2xl break-all">
        {{ props.query }}
      </div>
    </div>
  </div>
</template>

<style scoped></style>
