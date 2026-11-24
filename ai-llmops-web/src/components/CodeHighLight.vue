<script setup lang="ts">
import { onMounted, ref } from 'vue'
import hljs from 'highlight.js/lib/common'
import 'highlight.js/styles/github-dark.css'

const props = defineProps({
  language: {
    type: String,
    default: '',
    required: true,
  },
})

const codeElement = ref(null)

onMounted(() => {
  if (codeElement.value) {
    hljs.highlightElement(codeElement.value)
  }
})
</script>

<template>
  <pre
    class="m-0 p-0 overflow-hidden rounded-md"
  ><code ref="codeElement" :class="`language-${props.language} whitespace-pre! overflow-auto max-h-[700px] block p-4`"><slot></slot></code></pre>
</template>

<style scoped>
code::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
code::-webkit-scrollbar-thumb {
  background-color: #5c6370;
  border-radius: 4px;
}
code::-webkit-scrollbar-track {
  background-color: transparent;
}
</style>
