<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    page: number
    pageSize: number
    total: number
  }>(),
  {},
)

const emit = defineEmits<{ 'update:page': [page: number] }>()

const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
</script>

<template>
  <div v-if="total > pageSize" class="pagination">
    <button class="btn ghost sm" :disabled="page <= 1" @click="emit('update:page', page - 1)">上一页</button>
    <span class="crumb">第 {{ page }} / {{ pages }} 页 · 共 {{ total }} 条</span>
    <button class="btn ghost sm" :disabled="page >= pages" @click="emit('update:page', page + 1)">下一页</button>
  </div>
</template>
