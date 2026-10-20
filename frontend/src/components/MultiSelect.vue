<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

interface Option {
  value: string
  label: string
}

const props = defineProps<{
  options: Option[]
  modelValue: string[]
  placeholder?: string
  width?: string
}>()
const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)

const summary = computed(() => {
  if (!props.modelValue.length) return props.placeholder || '全部'
  const labels = props.modelValue
    .map((value) => props.options.find((option) => option.value === value)?.label || value)
    .filter(Boolean)
  if (labels.length <= 2) return labels.join('、')
  return `${labels.slice(0, 2).join('、')} +${labels.length - 2}`
})

function toggle(value: string): void {
  const next = new Set(props.modelValue)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  emit('update:modelValue', [...next])
}

function clear(): void {
  emit('update:modelValue', [])
}

function onDocumentClick(event: MouseEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="root" class="multi-select" :style="{ width: width || 'auto' }">
    <button type="button" class="multi-trigger" @click="open = !open">
      <span :class="{ muted: !modelValue.length }">{{ summary }}</span>
      <span class="caret">▾</span>
    </button>
    <div v-if="open" class="multi-panel">
      <label v-for="option in options" :key="option.value" class="multi-option">
        <input
          type="checkbox"
          :checked="modelValue.includes(option.value)"
          @change="toggle(option.value)"
        />
        <span>{{ option.label }}</span>
      </label>
      <div v-if="!options.length" class="multi-empty">暂无可选项</div>
      <div class="multi-foot">
        <button type="button" class="btn ghost sm" @click="clear">清空</button>
        <button type="button" class="btn ghost sm" @click="open = false">收起</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.multi-select {
  position: relative;
  min-width: 118px;
}
.multi-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--card);
  color: var(--ink);
  font: inherit;
  font-size: 13.5px;
  cursor: pointer;
}
.multi-trigger .muted {
  color: var(--ink3);
}
.caret {
  color: var(--ink3);
  font-size: 11px;
}
.multi-panel {
  position: absolute;
  z-index: 30;
  top: calc(100% + 6px);
  left: 0;
  min-width: 200px;
  max-height: 280px;
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--card);
  box-shadow: var(--shadow);
}
.multi-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13.5px;
  cursor: pointer;
}
.multi-option:hover {
  background: #f3f6f5;
}
.multi-option input {
  accent-color: var(--teal);
}
.multi-empty {
  padding: 8px;
  color: var(--ink3);
  font-size: 13px;
}
.multi-foot {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--line);
}
</style>
