<script setup lang="ts">
import { useAppStore } from '../stores/app'

const store = useAppStore()
</script>

<template>
  <div class="toast-stack">
    <div v-for="toast in store.toasts" :key="toast.id" class="toast-item" :class="toast.type">
      {{ toast.message }}
    </div>
  </div>
</template>
