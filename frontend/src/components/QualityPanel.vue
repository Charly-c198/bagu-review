<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { QualityCheck, QualityIssue, QualityRisk } from '../api/types'
import Modal from '../components/Modal.vue'
import { useAppStore } from '../stores/app'
import { formatDateTime } from '../utils/labels'

const props = defineProps<{
  targetType: 'pending' | 'question' | 'knowledge'
  targetId: number
}>()
const emit = defineEmits<{ (event: 'checked', check: QualityCheck | null): void }>()

interface ManualIssueForm {
  type: QualityIssue['type']
  severity: QualityRisk
  description: string
  evidence: string
  suggestion: string
}

const store = useAppStore()
const checks = ref<QualityCheck[]>([])
const loading = ref(true)
const running = ref(false)
const retryingId = ref<number | null>(null)

const manualOpen = ref(false)
const manualSaving = ref(false)
const manualIssues = ref<ManualIssueForm[]>([])
const manualSummary = ref('')

const latest = computed(() => checks.value[0] || null)
const latestSuccess = computed(
  () => checks.value.find((check) => check.status === 'success') || null,
)
const manualRisk = computed<QualityRisk>(() => {
  if (manualIssues.value.some((issue) => issue.severity === 'high')) return 'high'
  if (manualIssues.value.some((issue) => issue.severity === 'medium')) return 'medium'
  return 'low'
})

const issueTypes: { value: QualityIssue['type']; label: string }[] = [
  { value: 'fact_error', label: '事实错误' },
  { value: 'outdated', label: '信息过时' },
  { value: 'ambiguous', label: '表述歧义' },
  { value: 'incomplete', label: '内容不完整' },
  { value: 'inconsistent', label: '知识不一致' },
  { value: 'duplicate', label: '重复冲突' },
  { value: 'other', label: '其他' },
]

const risks: { value: QualityRisk; label: string }[] = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]

function issueTypeText(type: string): string {
  return issueTypes.find((item) => item.value === type)?.label || type
}

function riskText(risk: string | null | undefined): string {
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '中风险'
  if (risk === 'low') return '低风险'
  return '未评估'
}

function riskTone(risk: string | null | undefined): string {
  if (risk === 'high') return 'orange'
  if (risk === 'medium') return 'amber'
  return 'green'
}

function errorText(code: string | null | undefined): string {
  const mapping: Record<string, string> = {
    AI_NOT_CONFIGURED: '未配置 AI，请设置 BAJIU_AI_BASE_URL / BAJIU_AI_API_KEY / BAJIU_AI_MODEL',
    AI_UNAVAILABLE: 'AI 服务不可用或超时',
    AI_SCHEMA_INVALID: 'AI 返回格式不合法',
    AI_BUDGET_EXCEEDED: '本月 AI token 预算已用完',
  }
  return mapping[code || ''] || code || '未知错误'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{ items: QualityCheck[] }>(
      withQuery('/quality-checks', {
        target_type: props.targetType,
        target_id: props.targetId,
        page_size: 10,
      }),
    )
    checks.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '质检记录加载失败', 'error')
    checks.value = []
  } finally {
    loading.value = false
  }
}

async function runAI(): Promise<void> {
  running.value = true
  try {
    const check = await api.post<QualityCheck>('/quality/check', {
      target_type: props.targetType,
      target_id: props.targetId,
      mode: 'ai',
    })
    store.toast('AI 质检完成', 'success')
    emit('checked', check)
  } catch (err: any) {
    store.toast(err?.message || 'AI 质检失败，可转人工质检', 'error')
    emit('checked', null)
  } finally {
    running.value = false
    await load()
  }
}

async function retry(check: QualityCheck): Promise<void> {
  retryingId.value = check.id
  try {
    const next = await api.post<QualityCheck>(`/quality-checks/${check.id}/retry`)
    store.toast('AI 质检重试完成', 'success')
    emit('checked', next)
  } catch (err: any) {
    store.toast(err?.message || '重试失败，可转人工质检', 'error')
  } finally {
    retryingId.value = null
    await load()
  }
}

function openManual(): void {
  manualIssues.value = [
    { type: 'incomplete', severity: 'low', description: '', evidence: '', suggestion: '' },
  ]
  manualSummary.value = ''
  manualOpen.value = true
}

function addIssue(): void {
  manualIssues.value.push({
    type: 'other',
    severity: 'low',
    description: '',
    evidence: '',
    suggestion: '',
  })
}

function removeIssue(index: number): void {
  manualIssues.value.splice(index, 1)
}

async function saveManual(): Promise<void> {
  const issues = manualIssues.value
    .filter(
      (issue) =>
        issue.description.trim() || issue.evidence.trim() || issue.suggestion.trim(),
    )
    .map((issue) => ({ ...issue, confidence: null }))
  manualSaving.value = true
  try {
    const check = await api.post<QualityCheck>('/quality/check', {
      target_type: props.targetType,
      target_id: props.targetId,
      mode: 'manual',
      issues,
      overall_risk: manualRisk.value,
      summary: manualSummary.value.trim() || undefined,
    })
    store.toast('人工质检已记录', 'success')
    manualOpen.value = false
    emit('checked', check)
  } catch (err: any) {
    store.toast(err?.message || '保存人工质检失败', 'error')
  } finally {
    manualSaving.value = false
    await load()
  }
}

onMounted(load)
watch(() => [props.targetType, props.targetId], load)
</script>

<template>
  <div class="quality-panel">
    <div class="quality-head">
      <template v-if="latest">
        <span
          v-if="latest.status === 'failed'"
          class="tag orange"
        >待人工质检</span>
        <span v-else class="tag" :class="riskTone(latest.overall_risk)">
          {{ riskText(latest.overall_risk) }}
        </span>
        <span class="tag" :class="latest.model === 'manual' ? 'blue' : 'teal'">
          {{ latest.model === 'manual' ? '人工' : 'AI' }}
        </span>
        <span class="list-sub">{{ formatDateTime(latest.created_at) }}</span>
      </template>
      <span v-else class="list-sub">尚未质检</span>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" :disabled="running" @click="runAI">
        {{ running ? 'AI 质检中…' : 'AI 质检' }}
      </button>
      <button class="btn ghost sm" @click="openManual">人工质检</button>
    </div>

    <div v-if="loading" class="list-sub">加载中…</div>
    <template v-else>
      <div v-if="latest?.status === 'failed'" class="quality-failed">
        <div>
          <b>AI 质检失败</b>
          <span class="list-sub"> · {{ errorText(latest.error_code) }}</span>
        </div>
        <button
          class="btn ghost sm"
          :disabled="retryingId === latest.id"
          @click="retry(latest)"
        >
          {{ retryingId === latest.id ? '重试中…' : '重试 AI' }}
        </button>
      </div>

      <div v-if="latestSuccess" class="quality-result">
        <div class="list-sub">
          最近一次成功结果{{ latest?.status === 'failed' ? '（较早）' : '' }}：
          {{ latestSuccess.summary || '无总结' }}
        </div>
        <div v-if="latestSuccess.issues.length" class="quality-issues">
          <div
            v-for="(issue, index) in latestSuccess.issues"
            :key="index"
            class="quality-issue"
          >
            <div>
              <span class="tag" :class="riskTone(issue.severity)">
                {{ issueTypeText(issue.type) }} · {{ riskText(issue.severity) }}
              </span>
              <span v-if="issue.confidence !== null" class="list-sub">
                置信度 {{ Math.round((issue.confidence || 0) * 100) }}%
              </span>
            </div>
            <div>{{ issue.description || '—' }}</div>
            <div v-if="issue.evidence" class="list-sub">证据：{{ issue.evidence }}</div>
            <div v-if="issue.suggestion" class="list-sub">建议：{{ issue.suggestion }}</div>
          </div>
        </div>
        <div v-else class="list-sub">未发现明显问题。</div>
      </div>

      <div v-else-if="!latest" class="list-sub">
        AI 不可用时可直接人工质检，结果与 AI 质检共用同一套记录和徽标。
      </div>
    </template>

    <Modal :open="manualOpen" title="人工质检" wide @close="manualOpen = false">
      <div class="quality-manual-form">
        <div
          v-for="(issue, index) in manualIssues"
          :key="index"
          class="quality-manual-issue"
        >
          <div class="form-grid">
            <div class="field">
              <label>问题类型</label>
              <select v-model="issue.type" class="select">
                <option v-for="item in issueTypes" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>严重度</label>
              <select v-model="issue.severity" class="select">
                <option v-for="item in risks" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </div>
            <div class="field full">
              <label>问题描述</label>
              <textarea v-model="issue.description" class="textarea" rows="2" />
            </div>
            <div class="field full">
              <label>证据（可选）</label>
              <textarea v-model="issue.evidence" class="textarea" rows="2" />
            </div>
            <div class="field full">
              <label>修改建议（可选）</label>
              <textarea v-model="issue.suggestion" class="textarea" rows="2" />
            </div>
          </div>
          <button class="btn danger-ghost sm" @click="removeIssue(index)">删除该问题</button>
        </div>
        <div class="quality-manual-tools">
          <button class="btn ghost sm" @click="addIssue">+ 添加问题</button>
          <span class="tag" :class="riskTone(manualRisk)">整体风险：{{ riskText(manualRisk) }}</span>
        </div>
        <div class="field full">
          <label>审查总结（可选）</label>
          <textarea v-model="manualSummary" class="textarea" rows="2" />
        </div>
      </div>
      <div class="form-actions">
        <button class="btn ghost" @click="manualOpen = false">取消</button>
        <button class="btn green" :disabled="manualSaving" @click="saveManual">
          {{ manualSaving ? '保存中…' : '保存人工质检' }}
        </button>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.quality-panel {
  padding: 10px 0 2px;
}
.quality-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.quality-failed {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid #f0cfc0;
  border-radius: 8px;
  background: var(--orange-bg);
}
.quality-result {
  padding: 8px 0 2px;
}
.quality-issues {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.quality-issue {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--card);
  font-size: 13.5px;
  line-height: 1.6;
}
.quality-manual-issue {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.quality-manual-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 10px;
}
</style>
