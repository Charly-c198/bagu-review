<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'

import AppSidebar from './components/AppSidebar.vue'
import ToastHost from './components/ToastHost.vue'
import TopBar from './components/TopBar.vue'
import { useAppStore } from './stores/app'

const route = useRoute()
const store = useAppStore()

onMounted(async () => {
  if (!store.token) return
  if (!store.user) {
    try {
      await store.fetchMe()
    } catch {
      return
    }
  }
  if (!store.tree.length) {
    try {
      await store.fetchTree()
      await store.loadBadges()
    } catch {
      // ignore
    }
  }
})
</script>

<template>
  <router-view v-if="route.meta.public" />
  <div v-else class="app">
    <AppSidebar />
    <div class="main-wrap">
      <TopBar />
      <main id="main">
        <router-view />
      </main>
    </div>
  </div>
  <ToastHost />
</template>
