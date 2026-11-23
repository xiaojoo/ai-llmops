<script setup lang="ts">
// 量子领域 logo：原子核 + 三条椭圆电子轨道（量子比特风格，青-紫渐变）
const props = withDefaults(
  defineProps<{
    size?: number
  }>(),
  { size: 36 },
)
</script>

<template>
  <svg
    :width="props.size"
    :height="props.size"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    class="quantum-logo"
  >
    <defs>
      <linearGradient id="quantumGrad" x1="6" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#22d3ee" />
        <stop offset="50%" stop-color="#818cf8" />
        <stop offset="100%" stop-color="#c084fc" />
      </linearGradient>
      <linearGradient id="quantumCore" x1="18" y1="18" x2="30" y2="30" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#67e8f9" />
        <stop offset="100%" stop-color="#a78bfa" />
      </linearGradient>
    </defs>

    <!-- 三条椭圆电子轨道（不同倾角） -->
    <ellipse
      cx="24" cy="24" rx="19" ry="7.5"
      stroke="url(#quantumGrad)"
      stroke-width="1.4"
      fill="none"
      transform="rotate(30 24 24)"
      opacity="0.9"
    />
    <ellipse
      cx="24" cy="24" rx="19" ry="7.5"
      stroke="url(#quantumGrad)"
      stroke-width="1.4"
      fill="none"
      transform="rotate(90 24 24)"
      opacity="0.9"
    />
    <ellipse
      cx="24" cy="24" rx="19" ry="7.5"
      stroke="url(#quantumGrad)"
      stroke-width="1.4"
      fill="none"
      transform="rotate(150 24 24)"
      opacity="0.9"
    />

    <!-- 轨道上的电子（量子比特态） -->
    <circle cx="39.5" cy="13.5" r="2.4" fill="#22d3ee" />
    <circle cx="8.5" cy="34.5" r="2.4" fill="#818cf8" />
    <circle cx="37" cy="33" r="2.4" fill="#c084fc" />

    <!-- 中心原子核 -->
    <circle cx="24" cy="24" r="8" stroke="url(#quantumCore)" stroke-width="1.3" fill="rgba(129,140,248,0.10)" />
    <circle cx="24" cy="24" r="3.2" fill="url(#quantumCore)" />
  </svg>
</template>

<style scoped>
.quantum-logo {
  display: block;
  filter: drop-shadow(0 0 6px rgba(34, 211, 238, 0.4));
}
</style>
