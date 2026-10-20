<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    rows: { label: string; value: number; color?: string }[]
    color?: string
  }>(),
  { color: '#0d7377' },
)

const max = computed(() => Math.max(1, ...props.rows.map((row) => row.value)))
</script>

<template>
  <div>
    <div v-if="!rows.length" class="empty">暂无数据</div>
    <div v-for="row in rows" :key="row.label" class="bar-row">
      <div class="bar-label">{{ row.label }}</div>
      <div class="bar-track">
        <div
          class="bar-fill"
          :style="{ width: `${Math.round((row.value / max) * 100)}%`, background: row.color || color }"
        ></div>
      </div>
      <div class="num bar-value">{{ row.value }}</div>
    </div>
  </div>
</template>
