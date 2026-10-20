<script setup lang="ts">
withDefaults(defineProps<{ value: number | null | undefined }>(), { value: 0 })
</script>

<template>
  <span class="difficulty-bars" :title="`难度 ${value || 0}/5`">
    <span
      v-for="index in 5"
      :key="index"
      class="difficulty-bar"
      :class="{ filled: index <= (value || 0) }"
    ></span>
  </span>
</template>
