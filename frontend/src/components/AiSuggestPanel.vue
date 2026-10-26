<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { AiSuggestion, ApplySuggestionResult } from '../api/types'
import { useAppStore } from '../stores/app'
import { formatDateTime } from '../utils/labels'

const props = defineProps<{
  kind: 'tagging' | 'mistake_analysis' | 'answer_polish'
  targetType: 'pending' | 'question' | 'knowledge'
  targetId: number
  /** 已由父组件加载好的建议列表（待审详情），避免重复请求。 */
  initial?: AiSuggestion[]
}>()
const emit = defineEmits<{
  (event: 'generated', suggestion: AiSuggestion | null): void
  (event: 'applied', result: ApplySuggestionResult): void
}>()

const store = useAppStore()
const suggestions = ref<AiSuggestion[]>([])
const loading = ref(true)
const running = ref(false)
const applyingId = ref<number | null>(null)
const consent = ref(false)
const userAnswer = ref('')

const titles: Record<string, string> = {
  tagging: 'AI 打标建议',
  mistake_analysis: 'AI 错题解析',
  answer_polish: 'AI 答案润色',
}
const runLabels: Record<string, string> = {
  tagging: '生成打标建议',
  mistake_analysis: '生成拓展解析',
  answer_polish: '生成润色建议',
}

const latest = computed(() => suggestions.value[0] || null)
const latestSuccess = computed(
  () => suggestions.value.find((row) => row.status === 'success') || null,
)
const latestApplied = computed(
  () => suggestions.value.find((row) => row.applied_at) || null,
)

function errorText(code: string | null | undefined): string {
  const mapping: Record<string, string> = {
    AI_NOT_CONFIGURED: '未配置 AI，请设置 BAJIU_AI_BASE_URL / BAJIU_AI_API_KEY / BAJIU_AI_MODEL',
    AI_UNAVAILABLE: 'AI 服务不可用或超时，可在设置页检查配置后重试',
    AI_SCHEMA_INVALID: 'AI 返回格式不合法，可重试',
    AI_BUDGET_EXCEEDED: '本月 AI token 预算已用完',
  }
  return mapping[code || ''] || code || '未知错误'
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return `${Math.round(value * 100)}%`
}

async function load(): Promise<void> {
  if (props.initial) {
    suggestions.value = props.initial.filter((row) => row.kind === props.kind)
    loading.value = false
    return
  }
  loading.value = true
  try {
    const data = await api.get<{ items: AiSuggestion[] }>(
      withQuery('/ai/suggestions', {
        kind: props.kind,
        target_type: props.targetType,
        target_id: props.targetId,
        limit: 10,
      }),
    )
    suggestions.value = data.items
  } catch (err: any) {
    store.toast(err?.message || 'AI 建议加载失败', 'error')
    suggestions.value = []
  } finally {
    loading.value = false
  }
}

async function generate(): Promise<void> {
  running.value = true
  try {
    const suggestion = await api.post<AiSuggestion>('/ai/suggestions', {
      kind: props.kind,
      target_type: props.targetType,
      target_id: props.targetId,
      user_answer: userAnswer.value.trim() || undefined,
      consent: consent.value,
    })
    store.toast('AI 建议已生成', 'success')
    emit('generated', suggestion)
  } catch (err: any) {
    store.toast(err?.message || 'AI 生成失败，可稍后重试', 'error')
    emit('generated', null)
  } finally {
    running.value = false
    await load()
  }
}

async function apply(suggestion: AiSuggestion): Promise<void> {
  applyingId.value = suggestion.id
  try {
    const result = await api.post<ApplySuggestionResult>(
      `/ai/suggestions/${suggestion.id}/apply`,
    )
    store.toast('建议已应用并保存', 'success')
    emit('applied', result)
  } catch (err: any) {
    store.toast(err?.message || '应用建议失败', 'error')
  } finally {
    applyingId.value = null
    await load()
  }
}

watch(
  () => [props.targetType, props.targetId, props.kind],
  () => {
    consent.value = false
    userAnswer.value = ''
    load()
  },
  { immediate: true },
)
</script>

<template>
  <div class="ai-suggest-panel">
    <div class="ai-suggest-head">
      <span class="ai-suggest-title">{{ titles[kind] }}</span>
      <template v-if="latestApplied">
        <span class="tag green">已应用 {{ formatDateTime(latestApplied.applied_at) }}</span>
      </template>
      <template v-else-if="latest?.status === 'failed'">
        <span class="tag orange">生成失败</span>
      </template>
      <template v-else-if="latestSuccess">
        <span class="tag teal">AI · {{ formatDateTime(latestSuccess.created_at) }}</span>
      </template>
      <span v-else class="list-sub">尚未生成</span>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" :disabled="running" @click="generate">
        {{ running ? '生成中…' : runLabels[kind] }}
      </button>
    </div>

    <template v-if="kind === 'mistake_analysis'">
      <div class="ai-consent">
        <label>
          <input v-model="consent" type="checkbox" />
          允许把本次作答原文发送给 AI（默认只发送题目内容与参考答案）
        </label>
        <textarea
          v-if="consent"
          v-model="userAnswer"
          class="textarea"
          rows="3"
          placeholder="可粘贴你的作答（可选）；不填写则只发送题目"
        />
      </div>
    </template>

    <div v-if="running" class="list-sub">AI 生成中，推理型模型可能需要数十秒…</div>
    <div v-else-if="loading" class="list-sub">加载中…</div>

    <div v-else-if="latest?.status === 'failed'" class="ai-suggest-failed">
      <b>AI 生成失败</b>
      <span class="list-sub"> · {{ errorText(latest.error_code) }}</span>
    </div>

    <div v-if="latestSuccess" class="ai-suggest-result">
      <div v-if="latestSuccess.applied_at" class="list-sub">
        {{ latestSuccess.applied_at === latest?.applied_at ? '当前显示的是已应用的版本' : '已应用的版本（供对比）' }}
      </div>

      <template v-if="kind === 'tagging'">
        <div class="ai-chip-row">
          <span
            v-for="tag in latestSuccess.result?.tags || []"
            :key="tag"
            class="tag teal"
          >{{ tag }}</span>
          <span v-if="latestSuccess.result?.category_path" class="tag gray">
            {{ latestSuccess.result?.category_path }}
          </span>
          <span v-if="latestSuccess.result?.difficulty" class="tag gray">
            难度 {{ latestSuccess.result?.difficulty }}
          </span>
          <span v-if="latestSuccess.result?.frequency" class="tag amber">
            {{ latestSuccess.result?.frequency === 'high' ? '高频' : latestSuccess.result?.frequency === 'mid' ? '中频' : '低频' }}
          </span>
          <span v-if="latestSuccess.result?.confidence !== null" class="list-sub">
            置信度 {{ percent(latestSuccess.result?.confidence) }}
          </span>
        </div>
        <div v-if="latestSuccess.result?.rationale" class="list-sub">
          {{ latestSuccess.result?.rationale }}
        </div>
        <div class="ai-suggest-actions">
          <button
            class="btn green sm"
            :disabled="!!latestSuccess.applied_at || applyingId === latestSuccess.id"
            @click="apply(latestSuccess)"
          >
            {{ latestSuccess.applied_at ? '已应用' : applyingId === latestSuccess.id ? '应用中…' : '应用到建议元数据' }}
          </button>
          <span class="list-sub">应用后可在「编辑」中继续调整，再通过入库。</span>
        </div>
      </template>

      <template v-else-if="kind === 'mistake_analysis'">
        <div class="ai-suggest-block">{{ latestSuccess.result?.explanation || '—' }}</div>
        <template v-if="latestSuccess.result?.pitfalls?.length">
          <div class="ai-suggest-sub">易错点</div>
          <ul class="ai-suggest-list">
            <li v-for="(pitfall, index) in latestSuccess.result?.pitfalls" :key="index">
              {{ pitfall }}
            </li>
          </ul>
        </template>
        <template v-if="latestSuccess.result?.follow_ups?.length">
          <div class="ai-suggest-sub">自测追问</div>
          <ol class="ai-suggest-list">
            <li v-for="(item, index) in latestSuccess.result?.follow_ups" :key="index">
              {{ item }}
            </li>
          </ol>
        </template>
        <template v-if="latestSuccess.result?.related_knowledge?.length">
          <div class="ai-suggest-sub">关联知识点</div>
          <div
            v-for="(item, index) in latestSuccess.result?.related_knowledge"
            :key="index"
            class="list-sub"
          >
            {{ item.title }} · {{ item.why }}
          </div>
        </template>
        <div class="list-sub">解析只作参考，不会修改题目。</div>
      </template>

      <template v-else-if="kind === 'answer_polish'">
        <div class="ai-suggest-block polished">{{ latestSuccess.result?.polished_answer || '—' }}</div>
        <template v-if="latestSuccess.result?.key_points?.length">
          <div class="ai-suggest-sub">面试要点</div>
          <ul class="ai-suggest-list">
            <li v-for="(point, index) in latestSuccess.result?.key_points" :key="index">
              {{ point }}
            </li>
          </ul>
        </template>
        <template v-if="latestSuccess.result?.changes?.length">
          <div class="list-sub">改写说明：{{ latestSuccess.result?.changes.join('；') }}</div>
        </template>
        <div class="ai-suggest-actions">
          <button
            class="btn green sm"
            :disabled="!!latestSuccess.applied_at || applyingId === latestSuccess.id"
            @click="apply(latestSuccess)"
          >
            {{ latestSuccess.applied_at ? '已应用' : applyingId === latestSuccess.id ? '应用中…' : '用润色结果替换答案' }}
          </button>
          <span class="list-sub">会覆盖当前参考答案与要点。</span>
        </div>
      </template>
    </div>

    <div v-else-if="!latest && !loading" class="list-sub">
      {{ kind === 'tagging'
        ? '规则打标之外，可让 AI 参考现有分类体系给出更细的分类与标签。'
        : kind === 'mistake_analysis'
          ? 'AI 会拓展讲解、列出易错点并生成追问。未配置 AI 时不影响刷题。'
          : '把答案改写为面试中可直接口述的版本，替换前可先预览。' }}
    </div>
  </div>
</template>

<style scoped>
.ai-suggest-panel {
  padding: 4px 0 2px;
}
.ai-suggest-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.ai-suggest-title {
  font-weight: 600;
  font-size: 14px;
}
.ai-consent {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 13.5px;
  color: var(--ink2);
}
.ai-suggest-failed {
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid #f0cfc0;
  border-radius: 8px;
  background: var(--orange-bg);
  font-size: 13.5px;
}
.ai-suggest-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ai-chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.ai-suggest-block {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--card);
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.7;
}
.ai-suggest-sub {
  font-weight: 600;
  font-size: 13.5px;
}
.ai-suggest-list {
  margin: 0;
  padding-left: 22px;
  font-size: 13.5px;
  line-height: 1.7;
}
.ai-suggest-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
</style>