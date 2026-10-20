<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAppStore } from '../stores/app'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const username = ref('admin')
const password = ref('admin123')
const error = ref('')
const loading = ref(false)

async function submit(): Promise<void> {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和口令'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await store.login(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect)
  } catch (err: any) {
    error.value = err?.message || '登录失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (store.token) router.replace('/dashboard')
})
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-mark">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M5 7h14M5 12h14M5 17h9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" />
          </svg>
        </div>
        <div>
          <div class="login-title">八股文智能复习系统</div>
          <div class="login-sub">本地优先 · 间隔重复 · 题库/知识库</div>
        </div>
      </div>

      <div v-if="error" class="login-error">{{ error }}</div>

      <form @submit.prevent="submit">
        <div class="field">
          <label for="username">用户名</label>
          <input id="username" v-model="username" class="input" autocomplete="username" />
        </div>
        <div class="field">
          <label for="password">口令</label>
          <input
            id="password"
            v-model="password"
            class="input"
            type="password"
            autocomplete="current-password"
          />
        </div>
        <button class="btn" style="width: 100%; justify-content: center" type="submit" :disabled="loading">
          {{ loading ? '登录中…' : '进入系统' }}
        </button>
      </form>

      <div class="login-foot">
        首次运行默认口令为 <b>admin / admin123</b>，可通过环境变量
        <span class="mono">APP_PASSWORD</span> 覆盖。服务默认仅监听 127.0.0.1。
      </div>
    </div>
  </div>
</template>
