<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    labels: string[]
    color?: string
    maxV?: number | null
    height?: number
  }>(),
  { color: '#0d7377', maxV: null, height: 210 },
)

const width = 720
const padding = { left: 40, right: 16, top: 18, bottom: 32 }

const max = computed(() => {
  if (props.maxV) return props.maxV
  return Math.max(1, ...props.values) * 1.2
})

const points = computed(() => {
  const innerWidth = width - padding.left - padding.right
  const innerHeight = props.height - padding.top - padding.bottom
  const denominator = Math.max(1, props.values.length - 1)
  return props.values.map((value, index) => ({
    x: padding.left + (innerWidth * index) / denominator,
    y: padding.top + innerHeight * (1 - value / max.value),
  }))
})

const polyline = computed(() => points.value.map((point) => `${point.x},${point.y}`).join(' '))

const area = computed(() => {
  if (!points.value.length) return ''
  const bottom = props.height - padding.bottom
  return `${padding.left},${bottom} ${polyline.value} ${width - padding.right},${bottom}`
})

const labelNodes = computed(() => {
  const denominator = Math.max(1, props.labels.length - 1)
  return props.labels.map((label, index) => ({
    label,
    x: padding.left + ((width - padding.left - padding.right) * index) / denominator,
  }))
})

const grid = computed(() => [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
  y: padding.top + (props.height - padding.top - padding.bottom) * ratio,
  value: Math.round(max.value * (1 - ratio)),
})))
</script>

<template>
  <svg
    :viewBox="`0 0 ${width} ${height}`"
    class="chart-svg"
    role="img"
    aria-label="趋势图"
  >
    <g>
      <template v-for="line in grid" :key="line.y">
        <line
          :x1="padding.left"
          :x2="width - padding.right"
          :y1="line.y"
          :y2="line.y"
          stroke="#e9eeee"
          stroke-width="1"
          stroke-dasharray="3 4"
        />
        <text :x="padding.left - 8" :y="line.y + 4" font-size="10" fill="#93a19e" text-anchor="end">
          {{ line.value }}
        </text>
      </template>
    </g>
    <polygon :points="area" :fill="color" opacity="0.08" />
    <polyline
      :points="polyline"
      fill="none"
      :stroke="color"
      stroke-width="2.5"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
    <circle
      v-for="(point, index) in points"
      :key="index"
      :cx="point.x"
      :cy="point.y"
      r="4"
      :fill="color"
    />
    <text
      v-for="node in labelNodes"
      :key="node.label"
      :x="node.x"
      :y="height - 10"
      font-size="12"
      fill="#93a19e"
      text-anchor="middle"
    >
      {{ node.label }}
    </text>
  </svg>
</template>
