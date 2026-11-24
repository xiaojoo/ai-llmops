<script setup lang="ts">
import BannerImage from '@/views/auth/components/BannerImage.vue'
import LoginForm from '@/views/auth/components/LoginForm.vue'
import TechLogo from '@/components/TechLogo.vue'
import ParticleText from '@/components/ParticleText.vue'
</script>

<template>
  <!-- 页面容器 -->
  <div class="flex h-screen bg-white">
    <!-- 顶部logo（量子图标 + 粒子文字动画，与 home 页一致） -->
    <div class="fixed top-5 left-[22px] z-50 flex items-center gap-2">
      <tech-logo :size="40" class="shrink-0" />
      <div class="w-[300px] md:w-[400px] h-10 overflow-hidden">
        <particle-text
          text="Quantum Computing"
          :particle-size="2"
          :density="3"
          color="#22d3ee"
          highlight-color="#a78bfa"
          :scatter="120"
          :gather-duration="1400"
          :stagger="360"
          :pointer-repel="20"
          :repel-radius="100"
          :idle-drift="0.6"
          trigger="mount"
          :font-size="'clamp(1.1rem, 2vw, 1.7rem)'"
          :font-weight="800"
          font-family="inherit"
          :glow="false"
          align="left"
          class="login-particle-title"
        />
      </div>
    </div>
    <!-- 左侧banner -->
    <banner-image />
    <!-- 右侧表单 -->
    <div class="relative flex flex-1 items-center justify-center pb-10">
      <!-- 登录表单 -->
      <login-form />
    </div>
  </div>
  <!-- 页面容器 -->
</template>

<style scoped>
/* 顶部 header 粒子文字：去掉组件默认的最小高度，贴合 40px 高的 logo 区 */
:deep(.login-particle-title.particle-text) {
  min-height: 0;
  height: 40px;
}
</style>
