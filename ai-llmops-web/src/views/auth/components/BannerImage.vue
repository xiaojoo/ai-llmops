<script setup lang="ts">
import microWorld1 from '@/assets/images/micro-world-1.png'
import microWorld2 from '@/assets/images/micro-world-2.png'

const carousels = [
  {
    id: 1,
    slogan: '开箱即用的高质量AI编排模版',
    subSlogan: '丰富的应用组件，覆盖大多数典型业务场景',
    image: microWorld1,
  },
  {
    id: 2,
    slogan: '零代码5分钟编排原始AI应用',
    subSlogan: '高效开发你的AI原始应用',
    image: microWorld2,
  },
]
</script>

<template>
  <div
    class="w-[550px] flex items-center justify-center bg-linear-to-tr from-[#1d2129] to-[#00308f]"
  >
    <a-carousel
      :arrow="false"
      :dot="true"
      :auto-play="true"
      :animation-name="'fade'"
      class="flex-1 h-full"
    >
      <a-carousel-item v-for="carousel in carousels" :key="carousel.id">
        <div class="relative w-full h-full overflow-hidden">
          <img
            :src="carousel.image"
            alt="Quantum Computing"
            class="absolute inset-0 w-full h-full object-cover opacity-60"
          />
          <div class="relative z-10 flex flex-col items-center justify-center h-full">
            <div class="text-2xl leading-7 font-bold text-gray-100 drop-shadow-[0_2px_8px_rgba(0,0,0,0.8)]">
              {{ carousel.slogan }}
            </div>
            <div class="mt-2 text-gray-400 leading-[22px] drop-shadow-[0_2px_6px_rgba(0,0,0,0.8)]">
              {{ carousel.subSlogan }}
            </div>
          </div>
        </div>
      </a-carousel-item>
    </a-carousel>
  </div>
</template>
