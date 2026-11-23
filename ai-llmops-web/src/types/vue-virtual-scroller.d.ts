declare module 'vue-virtual-scroller' {
  import type { App, Component } from 'vue'

  export const RecycleScroller: Component
  export const DynamicScroller: Component
  export const DynamicScrollerItem: Component

  export function install(app: App): void
}
