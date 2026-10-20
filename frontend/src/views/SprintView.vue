<script setup lang="ts">
import { computed, ref } from 'vue'

import { api } from '../api/client'
import type { Question } from '../api/types'
import { useAppStore } from '../stores/app'
import {
  formatDate,
  frequencyText,
  frequencyTone,
  masteryText,
  masteryTone,
  sourceText,
  sourceTone,
} from '../utils/labels'

const store = useAppStore()

const company = ref('')
const frequency = ref('')
const difficulty = ref('')
const limit = ref(10)
const starting = ref(false)

const queue = ref<Question[]>([])
const index = ref(0)
const active = ref(false)
const finished = ref(false)
const revealed = ref(false)
const detail = ref<Question | null>(null)
const rating = ref(false)

const current = computed(() => queue.value[index.value] || null)
const currentDetail = computed(() => detail.value || current.value)

async function start(): Promise<void> {
  starting.value = true
  try {
    const data = await api.post<{ items: Question[] }>('/practice/quiz', {
      category_id: store.boardParam,
      company: company.value || undefined,
      frequency: frequency.value || undefined,
      difficulty: difficulty.value ? Number(difficulty.value) : undefined,
      limit: limit.value,
      mode: 'sprint',
    })
    queue.value = data.items
    if (!queue.value.length) {
      store.toast('没有匹配的题目，放宽条件试试', 'info')
      return
    }
    active.value = true
    finished.value = false
    index.value = 0
    revealed.value = false
    detail.value = null
  } catch (err: any) {
    store.toast(err?.message || '冲刺组卷失败', 'error')
  } finally {
    starting.value = false
  }
}

async function reveal(): Promise<void> {
  if (!current.value) return
  try {
    detail.value = await api.get<Question>(`/questions/${current.value.id}`)
    revealed.value = true
  } catch (err: any) {
    store.toast(err?.message || '答案加载失败', 'error')
  }
}

async function rate(q: number): Promise<void> {
  if (!current.value || rating.value) return
  rating.value = true
  try {
    const result = await api.post<{
      schedule_applied: boolean
      schedule: { next_review_date: string | null }
    }>('/ratings', {
      question_id: current.value.id,
      q,
      mode: 'practice',
      sprint: true,
    })
    if (result.schedule_applied) {
      store.toast(`已更新掌握度，下次复习 ${formatDate(result.schedule.next_review_date)}`, 'success')
    } else {
      store.toast('冲刺模式默认不改变排程，已记录评分', 'info')
    }
    index.value += 1
    revealed.value = false
    detail.value = null
    if (index.value >= queue.value.length) {
      finished.value = true
      await store.loadBadges()
    }
  } catch (err: any) {
    store.toast(err?.message || '评分失败', 'error')
  } finally {
    rating.value = false
  }
}

function restart(): void {
  active.value = false
  finished.value = false
  queue.value = []
}
</script>

<template>
  <div>
    <template v-if="!active">
      <div class="section-title">冲刺组卷</div>
      <div class="card" style="max-width: 640px">
        <div class="board-banner" style="margin-bottom: 18px">
          <b>{{ store.boardName }}</b>
          <span>忽略到期日期，从匹配题中按频率优先抽题</span>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>公司</label>
            <input v-model="company" class="input" placeholder="如 字节、腾讯，留空不限" />
          </div>
          <div class="field">
            <label>考察频率</label>
            <select v-model="frequency" class="select">
              <option value="">全部频率</option>
              <option value="high">高频</option>
              <option value="mid">中频</option>
              <option value="low">低频</option>
            </select>
          </div>
          <div class="field">
            <label>难度</label>
            <select v-model="difficulty" class="select">
              <option value="">全部难度</option>
              <option value="1">1 入门</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5 困难</option>
            </select>
          </div>
          <div class="field">
            <label>题量</label>
            <select v-model.number="limit" class="select">
              <option :value="5">5 题</option>
              <option :value="10">10 题</option>
              <option :value="20">20 题</option>
            </select>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn" :disabled="starting" @click="start">
            {{ starting ? '组卷中…' : '开始冲刺' }}
          </button>
        </div>
        <div class="list-sub" style="margin-top: 12px">
          冲刺模式默认不改变排程；评“不熟”仍会重置排程并进入错题本，题目本来到期时按正常规则推进。
        </div>
      </div>
    </template>

    <div v-else class="practice-stage">
      <div v-if="finished" class="pcard" style="text-align: center; align-items: center">
        <div style="font-size: 44px; margin-bottom: 8px">🏁</div>
        <div style="font-size: 19px; font-weight: 700">冲刺完成</div>
        <div style="color: var(--ink2); margin: 8px 0 18px">共完成 {{ queue.length }} 题</div>
        <div style="display: flex; gap: 10px">
          <button class="btn ghost" @click="restart">重新选题</button>
          <button class="btn" @click="start">再来一轮</button>
        </div>
      </div>
      <template v-else-if="current">
        <div class="p-progress">考前冲刺 · 第 {{ index + 1 }} / {{ queue.length }} 题</div>
        <div class="pcard">
          <div class="p-meta">
            <span class="tag teal">{{ store.boardName }}</span>
            <span v-if="current.category_path" class="tag gray">{{ current.category_path }}</span>
            <span class="tag" :class="frequencyTone(current.frequency)">{{ frequencyText(current.frequency) }}</span>
            <span class="tag" :class="sourceTone(current.source_type)">{{ sourceText(current.source_type) }}</span>
            <span class="tag" :class="masteryTone(current.mastery)">{{ masteryText(current.mastery) }}</span>
          </div>
          <div class="p-stem">{{ current.stem }}</div>
          <div v-if="revealed && currentDetail" class="panswer">
            <b>参考答案：</b>{{ currentDetail.answer || '暂无参考答案' }}
            <template v-if="currentDetail.key_points?.length">
              <br /><br /><b>要点：</b>
              <span style="color: var(--ink3)">{{ currentDetail.key_points.join('；') }}</span>
            </template>
          </div>
          <div v-if="!revealed" class="rate-row">
            <button class="btn" style="max-width: 220px; margin: 0 auto; justify-content: center" @click="reveal">
              显示答案
            </button>
          </div>
          <div v-else class="rate-row">
            <button class="rate-btn hard" :disabled="rating" @click="rate(2)">不熟</button>
            <button class="rate-btn mid" :disabled="rating" @click="rate(4)">熟悉</button>
            <button class="rate-btn easy" :disabled="rating" @click="rate(5)">精通</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
