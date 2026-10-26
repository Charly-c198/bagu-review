<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { api, withQuery } from '../api/client'
import type {
  InterviewAnswerState,
  InterviewReport,
  InterviewSession,
  InterviewTurn,
} from '../api/types'
import Modal from '../components/Modal.vue'
import { useAppStore } from '../stores/app'

const store = useAppStore()

/* ---- 列表 ---- */
const sessions = ref<InterviewSession[]>([])
const listLoading = ref(true)

async function loadSessions(): Promise<void> {
  listLoading.value = true
  try {
    const data = await api.get<{ items: InterviewSession[] }>(
      withQuery('/interview/sessions', { limit: 10 }),
    )
    sessions.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '面试记录加载失败', 'error')
  } finally {
    listLoading.value = false
  }
}

/* ---- 开始面试 ---- */
const setupOpen = ref(false)
const starting = ref(false)
const setup = reactive({
  count: 5,
  duration_min: 30,
  category_ids: [] as number[],
  difficulties: [] as number[],
  frequencies: [] as string[],
  ai_consent: false,
})

const flatCategories = computed(() => {
  const result: { id: number; path: string; label: string }[] = []
  const walk = (nodes: typeof store.tree): void => {
    nodes.forEach((node) => {
      result.push({
        id: node.id,
        path: node.path,
        label: `${'　'.repeat(Math.max(0, node.level - 1))}${node.name}（${node.question_count}）`,
      })
      walk(node.children)
    })
  }
  walk(store.tree)
  return result
})

const frequencyOptions = [
  { value: 'high', label: '高频' },
  { value: 'mid', label: '中频' },
  { value: 'low', label: '低频' },
]
const difficultyOptions = [1, 2, 3, 4, 5]

function openSetup(): void {
  setup.category_ids = store.boardId ? [store.boardId] : []
  setupOpen.value = true
}

function toggleNumber(list: number[], value: number): void {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

function toggleString(list: string[], value: string): void {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

async function startInterview(): Promise<void> {
  starting.value = true
  try {
    const session = await api.post<InterviewSession>('/interview/sessions', {
      count: setup.count,
      duration_min: setup.duration_min,
      category_ids: setup.category_ids,
      difficulties: setup.difficulties,
      frequencies: setup.frequencies,
      ai_consent: setup.ai_consent,
    })
    setupOpen.value = false
    await openSession(session.id)
    await loadSessions()
  } catch (err: any) {
    store.toast(err?.message || '开始面试失败', 'error')
  } finally {
    starting.value = false
  }
}

/* ---- 面试进行中 ---- */
const session = ref<InterviewSession | null>(null)
const states = reactive<Record<number, InterviewAnswerState>>({})
const currentIndex = ref(0)
const remainingSec = ref(0)
const loadLoading = ref(false)
const finishing = ref(false)
const submitting = ref(false)
const revealReference = ref(false)
let timer: number | null = null

const questions = computed(() => session.value?.questions || [])
const currentQuestion = computed(() => questions.value[currentIndex.value] || null)
const currentState = computed(() =>
  currentQuestion.value ? states[currentQuestion.value.id] : undefined,
)
const isRunning = computed(() => session.value?.status === 'in_progress')
const answeredCount = computed(
  () => Object.values(states).filter((state) => state.status !== 'draft').length,
)
const pendingCount = computed(
  () => Object.values(states).filter((state) => state.status === 'pending').length,
)
const scoredCount = computed(
  () => Object.values(states).filter((state) => state.turn?.score !== null && state.turn?.score !== undefined).length,
)

const timeText = computed(() => {
  const total = Math.max(0, remainingSec.value)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

function startTimer(secondsLeft: number): void {
  stopTimer()
  remainingSec.value = secondsLeft
  timer = window.setInterval(() => {
    if (remainingSec.value > 0) remainingSec.value -= 1
    if (remainingSec.value <= 0) stopTimer()
  }, 1000)
}

function stopTimer(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function remainingFrom(sessionValue: InterviewSession): number {
  const duration = (sessionValue.config?.duration_min || 30) * 60
  const elapsed = Math.floor((Date.now() - new Date(sessionValue.started_at).getTime()) / 1000)
  return Math.max(0, duration - elapsed)
}

function buildState(turn: InterviewTurn): InterviewAnswerState {
  return {
    status: 'scored',
    answer_text: turn.answer_text,
    score: turn.score ?? '',
    feedback: turn.feedback || '',
    turn,
  }
}

async function openSession(sessionId: number): Promise<void> {
  loadLoading.value = true
  stopTimer()
  revealReference.value = false
  try {
    const data = await api.get<InterviewSession>(`/interview/sessions/${sessionId}`)
    session.value = data
    Object.keys(states).forEach((key) => delete states[Number(key)])
    ;(data.turns || []).forEach((turn) => {
      states[turn.question_id] = buildState(turn)
    })
    ;(data.questions || []).forEach((question) => {
      if (!states[question.id]) {
        states[question.id] = {
          status: 'draft',
          answer_text: '',
          score: '',
          feedback: '',
          turn: null,
        }
      }
    })
    const firstUnanswered = (data.questions || []).findIndex(
      (question) => states[question.id]?.status === 'draft',
    )
    currentIndex.value = firstUnanswered >= 0 ? firstUnanswered : 0
    if (data.status === 'in_progress') startTimer(remainingFrom(data))
    if (data.report) report.value = data.report
  } catch (err: any) {
    store.toast(err?.message || '面试详情加载失败', 'error')
  } finally {
    loadLoading.value = false
  }
}

async function submitCurrent(): Promise<void> {
  if (!session.value || !currentQuestion.value) return
  const questionId = currentQuestion.value.id
  const state = states[questionId]
  if (!state) return
  if (!state.answer_text.trim()) {
    store.toast('请先输入作答内容', 'error')
    return
  }
  state.status = 'pending'
  submitting.value = true
  try {
    const turn = await api.post<InterviewTurn>(
      `/interview/sessions/${session.value.id}/answers`,
      {
        question_id: questionId,
        answer_text: state.answer_text.trim(),
      },
    )
    states[questionId] = {
      ...state,
      status: 'scored',
      score: turn.score ?? '',
      feedback: turn.feedback || '',
      turn,
    }
    store.toast(turn.scored_by === 'ai' ? '作答已提交并完成 AI 评分' : '作答已保存，可手动评分', 'success')
    // 留在当前题展示评分与追问，由考生手动切换下一题，避免评分还没看就跳走。
    const start = questions.value.findIndex((question) => question.id === questionId)
    const remaining = questions.value.filter(
      (question, index) => index > start && states[question.id]?.status === 'draft',
    ).length
    if (remaining) {
      store.toast(`还有 ${remaining} 道未作答，可点击「下一题」继续`, 'info')
    }
  } catch (err: any) {
    // AI 评分失败时作答已落库，降级为手动评分。
    const savedTurn: InterviewTurn | undefined = err?.data?.turn
    if (savedTurn) {
      states[questionId] = {
        status: 'scored',
        answer_text: state.answer_text,
        score: savedTurn.score ?? '',
        feedback: savedTurn.feedback || '',
        turn: savedTurn,
      }
    } else {
      state.status = 'draft'
      if (session.value) await openSession(session.value.id)
    }
    const reason =
      err?.code === 'AI_NOT_CONFIGURED'
        ? '未配置 AI：作答已保存，请手动评分'
        : `${err?.message || 'AI 评分失败'}：作答已保存，可手动评分`
    store.toast(reason, 'error')
  } finally {
    submitting.value = false
  }
}

async function saveManualScore(questionId: number): Promise<void> {
  if (!session.value) return
  const state = states[questionId]
  if (!state?.turn) {
    store.toast('请先提交作答再评分', 'error')
    return
  }
  if (state.score === '') {
    store.toast('请选择 0–5 分', 'error')
    return
  }
  try {
    const turn = await api.patch<InterviewTurn>(
      `/interview/sessions/${session.value.id}/turns/${state.turn.id}`,
      { score: Number(state.score), feedback: state.feedback || undefined },
    )
    states[questionId] = buildState(turn)
    store.toast('评分已保存', 'success')
  } catch (err: any) {
    store.toast(err?.message || '评分保存失败', 'error')
  }
}

async function saveFollowUp(questionId: number): Promise<void> {
  if (!session.value) return
  const state = states[questionId]
  const answer = (followUpDrafts[questionId] || '').trim()
  if (!state?.turn || !answer) {
    store.toast('请输入追问作答', 'error')
    return
  }
  try {
    const turn = await api.post<InterviewTurn>(
      `/interview/sessions/${session.value.id}/turns/${state.turn.id}/follow-up`,
      { answer_text: answer },
    )
    states[questionId] = { ...state, turn }
    store.toast('追问作答已保存', 'success')
  } catch (err: any) {
    store.toast(err?.message || '追问保存失败', 'error')
  }
}

const followUpDrafts = reactive<Record<number, string>>({})

/* ---- 结束与报告 ---- */
const report = ref<InterviewReport | null>(null)
const reportOpen = ref(false)

async function finish(): Promise<void> {
  if (!session.value) return
  if (!scoredCount.value) {
    store.toast('至少完成并评分一道题后才能结束面试', 'error')
    return
  }
  if (!window.confirm(`确定结束面试？已评分 ${scoredCount.value}/${questions.value.length} 题，未评分题目不计入报告。`)) {
    return
  }
  finishing.value = true
  try {
    const data = await api.post<{ report: InterviewReport; session: InterviewSession }>(
      `/interview/sessions/${session.value.id}/finish`,
    )
    report.value = data.report
    session.value = data.session
    reportOpen.value = true
    stopTimer()
    const message =
      data.report.generated_by === 'ai'
        ? '面试复盘已生成，薄弱题目已写入错题本与复习队列'
        : data.report.ai_error_code
          ? `AI 复盘不可用（${data.report.ai_error_code}），已生成基础报告`
          : '面试复盘已生成'
    store.toast(message, 'success')
    await Promise.all([loadSessions(), store.loadBadges()])
  } catch (err: any) {
    store.toast(err?.message || '结束面试失败', 'error')
  } finally {
    finishing.value = false
  }
}

async function abort(): Promise<void> {
  if (!session.value) return
  if (!window.confirm('中止后本次面试不能继续作答，已提交的作答会保留。确定中止？')) return
  try {
    await api.post(`/interview/sessions/${session.value.id}/abort`)
    store.toast('面试已中止', 'info')
    session.value = null
    stopTimer()
    await loadSessions()
  } catch (err: any) {
    store.toast(err?.message || '中止失败', 'error')
  }
}

async function viewReport(item: InterviewSession): Promise<void> {
  await openSession(item.id)
  if (session.value?.report) {
    report.value = session.value.report
    reportOpen.value = true
  }
}

function resume(item: InterviewSession): void {
  openSession(item.id)
}

function scoreTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'gray'
  if (score >= 4) return 'green'
  if (score >= 3) return 'amber'
  return 'orange'
}

function statusText(status: string): string {
  if (status === 'in_progress') return '进行中'
  if (status === 'finished') return '已完成'
  return '已中止'
}

onMounted(loadSessions)
onBeforeUnmount(stopTimer)
</script>

<template>
  <div class="interview-page">
    <div class="toolbar">
      <button class="btn" @click="openSetup">+ 开始仿真面试</button>
      <button class="btn ghost sm" @click="loadSessions">刷新</button>
      <div style="flex: 1"></div>
      <span class="tag gray">文字作答 · 默认本地评分，AI 需显式同意</span>
    </div>

    <div v-if="loadLoading && !session" class="card empty">加载中…</div>

    <!-- 进行中 -->
    <template v-else-if="session && isRunning">
      <div class="board-banner">
        <b>仿真面试</b>
        <span>
          {{ questions.length }} 题 · 已作答 {{ answeredCount }} · 已评分 {{ scoredCount }}
          <template v-if="pendingCount"> · AI 评分中 {{ pendingCount }}</template>
        </span>
        <span class="tag" :class="remainingSec < 300 ? 'orange' : 'teal'">剩余 {{ timeText }}</span>
        <div style="flex: 1"></div>
        <button class="btn ghost sm" @click="abort">中止</button>
        <button class="btn green sm" :disabled="finishing || !scoredCount" @click="finish">
          {{ finishing ? '生成报告中…' : '结束面试并生成报告' }}
        </button>
      </div>

      <div class="interview-grid">
        <div class="iv-nav card">
          <div
            v-for="(question, index) in questions"
            :key="question.id"
            class="iv-nav-item"
            :class="{ active: index === currentIndex }"
            @click="currentIndex = index"
          >
            <span class="iv-nav-index">{{ index + 1 }}</span>
            <span class="iv-nav-dot" :class="states[question.id]?.status || 'draft'" />
            <span class="iv-nav-stem">{{ question.stem }}</span>
          </div>
        </div>

        <div v-if="currentQuestion" class="card iv-main">
          <div class="iv-meta">
            <span class="tag teal">第 {{ currentIndex + 1 }} / {{ questions.length }} 题</span>
            <span v-if="currentQuestion.difficulty" class="tag gray">难度 {{ currentQuestion.difficulty }}</span>
            <span v-if="currentQuestion.category_path" class="tag gray">{{ currentQuestion.category_path }}</span>
          </div>
          <h3 class="iv-stem">{{ currentQuestion.stem }}</h3>

          <template v-if="currentState">
            <textarea
              v-if="!currentState.turn"
              v-model="currentState.answer_text"
              class="textarea iv-answer"
              rows="10"
              placeholder="用面试口述的方式作答：先给结论，再讲原理、流程与边界。"
            />
            <div v-else class="iv-answer-readonly">{{ currentState.turn.answer_text }}</div>

            <div v-if="!currentState.turn" class="form-actions" style="justify-content: flex-start">
              <button
                class="btn green"
                :disabled="currentState.status === 'pending'"
                @click="submitCurrent"
              >
                {{ currentState.status === 'pending' ? 'AI 评分中…' : '提交作答' }}
              </button>
              <span class="list-sub">
                未同意发送作答时只保存作答，提交后可手动评分。
              </span>
            </div>

            <template v-if="currentState.turn">
              <div v-if="currentState.turn" class="iv-score-row">
                <span class="tag" :class="scoreTone(currentState.turn.score)">
                  {{ currentState.turn.scored_by === 'ai' ? 'AI 评分' : currentState.turn.scored_by === 'manual' ? '手动评分' : '未评分' }}
                </span>
                <div v-if="isRunning" class="iv-manual-score">
                  <select v-model="currentState.score" class="select iv-score-select">
                    <option value="">未选择</option>
                    <option v-for="n in [0, 1, 2, 3, 4, 5]" :key="n" :value="n">{{ n }} 分</option>
                  </select>
                  <button class="btn ghost sm" @click="saveManualScore(currentQuestion.id)">
                    {{ currentState.turn.scored_by === 'none' ? '保存评分' : '手动改分' }}
                  </button>
                  <span v-if="currentState.turn.score !== null" class="iv-score">
                    {{ currentState.turn.score }}<small>/5</small>
                  </span>
                </div>
                <span v-else-if="currentState.turn.score !== null" class="iv-score">
                  {{ currentState.turn.score }}<small>/5</small>
                </span>
              </div>

              <div v-if="currentState.turn.feedback" class="iv-feedback">
                <div class="iv-label">面试官反馈</div>
                <div>{{ currentState.turn.feedback }}</div>
                <div v-if="currentState.turn.gaps.length" class="list-sub" style="margin-top: 6px">
                  缺失要点：{{ currentState.turn.gaps.join('；') }}
                </div>
              </div>

              <div v-if="currentState.turn.follow_up" class="iv-follow">
                <div class="iv-label">追问</div>
                <div>{{ currentState.turn.follow_up }}</div>
                <textarea
                  v-if="!currentState.turn.follow_up_answer"
                  v-model="followUpDrafts[currentQuestion.id]"
                  class="textarea"
                  rows="3"
                  placeholder="补充回答（可选）"
                />
                <div v-else class="list-sub">追问作答：{{ currentState.turn.follow_up_answer }}</div>
                <button
                  v-if="!currentState.turn.follow_up_answer"
                  class="btn ghost sm"
                  style="margin-top: 8px"
                  @click="saveFollowUp(currentQuestion.id)"
                >保存追问作答</button>
              </div>

              <div class="iv-reference">
                <button class="btn ghost sm" @click="revealReference = !revealReference">
                  {{ revealReference ? '隐藏参考答案' : '查看参考答案' }}
                </button>
                <template v-if="revealReference">
                  <div class="panswer" style="margin-top: 10px">
                    {{ currentState.turn.reference_answer || '暂无参考答案' }}
                    <template v-if="currentState.turn.reference_key_points?.length">
                      <br /><br /><b>要点：</b>{{ currentState.turn.reference_key_points.join('；') }}
                    </template>
                  </div>
                </template>
              </div>
            </template>
          </template>

          <div class="form-actions" style="justify-content: space-between; margin-top: 18px">
            <button class="btn ghost sm" :disabled="currentIndex === 0" @click="currentIndex -= 1">上一题</button>
            <button
              class="btn ghost sm"
              :disabled="currentIndex >= questions.length - 1"
              @click="currentIndex += 1"
            >下一题</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 历史记录 -->
    <div v-if="!session || !isRunning" class="section-title">面试记录</div>
    <div v-if="!session || !isRunning" class="card" style="padding: 6px 16px">
      <template v-if="sessions.length">
        <div v-for="item in sessions" :key="item.id" class="list-row">
          <div class="list-main">
            <div class="list-title">
              #{{ item.id }} · {{ item.config.count }} 题 · {{ item.config.duration_min }} 分钟
            </div>
            <div class="list-sub">
              {{ new Date(item.started_at).toLocaleString() }} ·
              {{ item.progress.answered }}/{{ item.progress.total }} 已作答 ·
              {{ item.config.ai_consent ? 'AI 评分已同意' : '仅手动评分' }}
            </div>
          </div>
          <span class="tag" :class="item.status === 'finished' ? 'green' : item.status === 'in_progress' ? 'amber' : 'gray'">
            {{ statusText(item.status) }}
          </span>
          <span v-if="item.total_score !== null && item.total_score !== undefined" class="iv-score">
            {{ item.total_score }}<small>分</small>
          </span>
          <button v-if="item.status === 'in_progress'" class="btn sm" @click="resume(item)">继续</button>
          <button v-else-if="item.status === 'finished'" class="btn ghost sm" @click="viewReport(item)">查看报告</button>
        </div>
      </template>
      <div v-else class="empty">还没有面试记录，点击「开始仿真面试」随机组卷</div>
    </div>

    <!-- 开始面试 -->
    <Modal :open="setupOpen" title="开始文字仿真面试" wide @close="setupOpen = false">
      <div class="form-grid">
        <div class="field">
          <label>题量</label>
          <select v-model.number="setup.count" class="select">
            <option v-for="n in [3, 5, 8, 10, 15]" :key="n" :value="n">{{ n }} 题</option>
          </select>
        </div>
        <div class="field">
          <label>时长（分钟）</label>
          <select v-model.number="setup.duration_min" class="select">
            <option v-for="n in [15, 20, 30, 45, 60, 90]" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <div class="field full">
          <label>范围（分类，可多选；不选则全部）</label>
          <select
            v-model="setup.category_ids"
            class="select"
            multiple
            size="6"
          >
            <option v-for="category in flatCategories" :key="category.id" :value="category.id">
              {{ category.label }}
            </option>
          </select>
        </div>
        <div class="field full">
          <label>难度（可多选；不选则不限）</label>
          <div class="iv-chips">
            <label v-for="value in difficultyOptions" :key="value" class="iv-chip">
              <input
                type="checkbox"
                :checked="setup.difficulties.includes(value)"
                @change="toggleNumber(setup.difficulties, value)"
              />
              {{ value }}
            </label>
          </div>
        </div>
        <div class="field full">
          <label>频率（可多选；不选则不限）</label>
          <div class="iv-chips">
            <label v-for="option in frequencyOptions" :key="option.value" class="iv-chip">
              <input
                type="checkbox"
                :checked="setup.frequencies.includes(option.value)"
                @change="toggleString(setup.frequencies, option.value)"
              />
              {{ option.label }}
            </label>
          </div>
        </div>
        <div class="field full">
          <label style="display: flex; align-items: flex-start; gap: 8px; font-weight: 400">
            <input v-model="setup.ai_consent" type="checkbox" style="margin-top: 3px" />
            <span>
              同意把本次面试的文字作答发送给 AI 进行评分与复盘。
              不勾选时作答只保存在本地，需手动评分，报告为基础版。
            </span>
          </label>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn ghost" @click="setupOpen = false">取消</button>
        <button class="btn green" :disabled="starting" @click="startInterview">
          {{ starting ? '组卷中…' : '随机组卷并开始' }}
        </button>
      </div>
    </Modal>

    <!-- 报告 -->
    <Modal :open="reportOpen" title="面试复盘报告" wide @close="reportOpen = false">
      <template v-if="report">
        <div class="iv-report-head">
          <div class="iv-score big">{{ report.total_score }}<small>分</small></div>
          <div>
            <div class="list-sub">
              平均 {{ report.average_score }}/5 · 已评分 {{ report.scored }}/{{ report.total }} ·
              {{ report.generated_by === 'ai' ? 'AI 复盘' : '基础报告' }}
            </div>
            <span v-if="report.ai_error_code" class="tag amber">
              AI 不可用（{{ report.ai_error_code }}），已降级
            </span>
          </div>
        </div>
        <p class="iv-summary">{{ report.summary }}</p>

        <div class="iv-report-grid">
          <div>
            <div class="iv-label">亮点</div>
            <ul class="iv-list"><li v-for="(item, index) in report.highlights" :key="index">{{ item }}</li></ul>
          </div>
          <div>
            <div class="iv-label">知识缺口</div>
            <ul class="iv-list"><li v-for="(item, index) in report.gaps" :key="index">{{ item }}</li></ul>
          </div>
        </div>

        <div class="iv-label">改进建议</div>
        <ul class="iv-list"><li v-for="(item, index) in report.advice" :key="index">{{ item }}</li></ul>

        <div class="iv-label" style="margin-top: 12px">下一步</div>
        <ul class="iv-list"><li v-for="(item, index) in report.next_steps" :key="index">{{ item }}</li></ul>

        <div class="iv-label" style="margin-top: 14px">逐题得分</div>
        <div v-for="row in report.per_question" :key="row.question_id" class="list-row">
          <span class="tag" :class="scoreTone(row.score)">
            {{ row.score === null ? '未评分' : `${row.score}/5` }}
          </span>
          <div class="list-main">
            <div class="list-title">第 {{ row.index }} 题 · {{ row.stem }}</div>
            <div v-if="row.feedback" class="list-sub">{{ row.feedback }}</div>
          </div>
          <span
            v-if="report.weak_question_ids.includes(row.question_id)"
            class="tag orange"
          >已加入错题本</span>
        </div>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.interview-grid {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  align-items: start;
}
.iv-nav {
  padding: 8px;
  max-height: 70vh;
  overflow-y: auto;
}
.iv-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.iv-nav-item:hover {
  background: var(--bg);
}
.iv-nav-item.active {
  background: var(--teal-bg);
  color: var(--teal-d);
  font-weight: 600;
}
.iv-nav-index {
  width: 20px;
  text-align: right;
  color: var(--ink3);
  flex-shrink: 0;
}
.iv-nav-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d5dcd9;
  flex-shrink: 0;
}
.iv-nav-dot.pending {
  background: var(--amber);
}
.iv-nav-dot.scored {
  background: var(--green);
}
.iv-nav-stem {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.iv-main {
  padding: 20px 22px;
}
.iv-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.iv-stem {
  font-size: 18px;
  line-height: 1.6;
  margin-bottom: 14px;
}
.iv-answer {
  min-height: 200px;
}
.iv-answer-readonly {
  padding: 14px 16px;
  background: var(--bg);
  border-radius: 10px;
  white-space: pre-wrap;
  font-size: 14.5px;
  color: var(--ink2);
}
.iv-score-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.iv-score {
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
}
.iv-score.big {
  font-size: 40px;
  color: var(--teal-d);
}
.iv-score small {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink3);
  margin-left: 2px;
}
.iv-score-select {
  width: 120px;
}
.iv-manual-score {
  display: flex;
  align-items: center;
  gap: 10px;
}
.iv-feedback,
.iv-follow {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.7;
}
.iv-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink2);
  margin-bottom: 6px;
}
.iv-reference {
  margin-top: 14px;
}
.iv-report-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
}
.iv-summary {
  margin: 10px 0 14px;
  font-size: 14.5px;
  line-height: 1.7;
  color: var(--ink2);
}
.iv-report-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 10px;
}
.iv-list {
  margin: 0 0 10px;
  padding-left: 20px;
  font-size: 13.5px;
  line-height: 1.7;
}
.iv-chips {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.iv-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
}
@media (max-width: 960px) {
  .interview-grid {
    grid-template-columns: 1fr;
  }
}
</style>