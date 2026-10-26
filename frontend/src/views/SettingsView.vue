<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import type { AIStatus, Settings, TagRule } from '../api/types'
import Modal from '../components/Modal.vue'
import { useAppStore } from '../stores/app'
import {
  formatDateTime,
  frequencyText,
  frequencyTone,
} from '../utils/labels'

const store = useAppStore()
const router = useRouter()

const settings = ref<Settings | null>(null)
const loading = ref(true)
const saving = ref(false)
const rules = ref<TagRule[]>([])
const tags = ref<{ id: number; name: string }[]>([])
const backups = ref<{ name: string; size: number; modified_at: string }[]>([])
const rulesLoading = ref(true)
const aiStatus = ref<AIStatus | null>(null)

const ruleOpen = ref(false)
const ruleSaving = ref(false)
const editingRuleId = ref<number | null>(null)
const ruleForm = reactive({
  keyword: '',
  match_type: 'contains',
  tag_id: null as number | null,
  category_id: null as number | null,
  difficulty: '' as number | '',
  frequency: '',
  weight: 1,
  enabled: true,
})

const restoreFile = ref<File | null>(null)
const restoreConfirm = ref(false)
const restoring = ref(false)
const restoreInput = ref<HTMLInputElement | null>(null)

const flatCategories = computed(() => {
  const result: { id: number; path: string }[] = []
  const walk = (nodes: typeof store.tree): void => {
    nodes.forEach((node) => {
      result.push({ id: node.id, path: node.path })
      walk(node.children)
    })
  }
  walk(store.tree)
  return result
})

async function loadSettings(): Promise<void> {
  loading.value = true
  try {
    settings.value = await api.get<Settings>('/settings')
  } catch (err: any) {
    store.toast(err?.message || '设置加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function saveSettings(): Promise<void> {
  if (!settings.value) return
  saving.value = true
  try {
    settings.value = await api.patch<Settings>('/settings', settings.value)
    store.toast('设置已保存', 'success')
  } catch (err: any) {
    store.toast(err?.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function loadRules(): Promise<void> {
  rulesLoading.value = true
  try {
    const [ruleData, tagData] = await Promise.all([
      api.get<TagRule[]>('/tag-rules'),
      api.get<{ id: number; name: string }[]>('/tags'),
    ])
    rules.value = ruleData
    tags.value = tagData
  } catch (err: any) {
    store.toast(err?.message || '规则加载失败', 'error')
  } finally {
    rulesLoading.value = false
  }
}

async function loadBackups(): Promise<void> {
  try {
    backups.value = await api.get('/backup/list')
  } catch {
    backups.value = []
  }
}

async function loadAIStatus(): Promise<void> {
  try {
    aiStatus.value = await api.get<AIStatus>('/ai/status')
  } catch {
    aiStatus.value = null
  }
}

function openRule(rule?: TagRule): void {
  if (rule) {
    editingRuleId.value = rule.id
    ruleForm.keyword = rule.keyword
    ruleForm.match_type = rule.match_type
    ruleForm.tag_id = rule.tag_id
    ruleForm.category_id = rule.category_id
    ruleForm.difficulty = rule.difficulty ?? ''
    ruleForm.frequency = rule.frequency || ''
    ruleForm.weight = rule.weight
    ruleForm.enabled = rule.enabled
  } else {
    editingRuleId.value = null
    ruleForm.keyword = ''
    ruleForm.match_type = 'contains'
    ruleForm.tag_id = null
    ruleForm.category_id = null
    ruleForm.difficulty = ''
    ruleForm.frequency = ''
    ruleForm.weight = 1
    ruleForm.enabled = true
  }
  ruleOpen.value = true
}

async function saveRule(): Promise<void> {
  if (!ruleForm.keyword.trim()) {
    store.toast('关键词不能为空', 'error')
    return
  }
  ruleSaving.value = true
  const payload: Record<string, unknown> = {
    keyword: ruleForm.keyword.trim(),
    match_type: ruleForm.match_type,
    category_id: ruleForm.category_id,
    difficulty: ruleForm.difficulty === '' ? null : Number(ruleForm.difficulty),
    frequency: ruleForm.frequency || null,
    weight: Number(ruleForm.weight),
    enabled: ruleForm.enabled,
  }
  try {
    if (editingRuleId.value) {
      await api.patch(`/tag-rules/${editingRuleId.value}`, {
        ...payload,
        tag_id: ruleForm.tag_id,
      })
      store.toast('规则已保存', 'success')
    } else {
      await api.post('/tag-rules', {
        ...payload,
        tag_ids: ruleForm.tag_id ? [ruleForm.tag_id] : [],
      })
      store.toast('规则已创建', 'success')
    }
    ruleOpen.value = false
    await loadRules()
  } catch (err: any) {
    store.toast(err?.message || '保存规则失败', 'error')
  } finally {
    ruleSaving.value = false
  }
}

async function toggleRule(rule: TagRule): Promise<void> {
  try {
    await api.patch(`/tag-rules/${rule.id}`, { enabled: !rule.enabled })
    await loadRules()
  } catch (err: any) {
    store.toast(err?.message || '操作失败', 'error')
  }
}

async function deleteRule(rule: TagRule): Promise<void> {
  if (!window.confirm(`删除规则「${rule.keyword}」？`)) return
  try {
    await api.delete(`/tag-rules/${rule.id}`)
    store.toast('规则已删除', 'success')
    await loadRules()
  } catch (err: any) {
    store.toast(err?.message || '删除失败', 'error')
  }
}

async function exportData(format: 'json' | 'md'): Promise<void> {
  try {
    await api.download(`/export?format=${format}`)
    store.toast('导出已开始下载', 'success')
  } catch (err: any) {
    store.toast(err?.message || '导出失败', 'error')
  }
}

async function backup(): Promise<void> {
  try {
    await api.download('/backup/export', { method: 'POST' })
    store.toast('备份已开始下载', 'success')
    await loadBackups()
  } catch (err: any) {
    store.toast(err?.message || '备份失败', 'error')
  }
}

function onRestoreChange(event: Event): void {
  const target = event.target as HTMLInputElement
  restoreFile.value = target.files?.[0] || null
  restoreConfirm.value = false
}

async function restore(): Promise<void> {
  if (!restoreFile.value) {
    store.toast('请选择备份文件', 'error')
    return
  }
  if (!restoreConfirm.value) {
    store.toast('请勾选确认覆盖当前数据库', 'error')
    return
  }
  restoring.value = true
  const form = new FormData()
  form.append('file', restoreFile.value)
  form.append('confirm', 'true')
  try {
    await api.upload('/backup/import', form)
    store.toast('恢复完成，页面将在 2 秒后刷新', 'success')
    window.setTimeout(() => window.location.reload(), 2000)
  } catch (err: any) {
    store.toast(err?.message || '恢复失败', 'error')
  } finally {
    restoring.value = false
  }
}

async function logout(): Promise<void> {
  await store.logout()
  router.replace('/login')
}

onMounted(async () => {
  await Promise.all([loadSettings(), loadRules(), loadBackups(), loadAIStatus()])
})
</script>

<template>
  <div>
    <div v-if="loading" class="card empty">加载中…</div>
    <template v-else-if="settings">
      <div class="section-title">SM-2 间隔重复参数</div>
      <div class="card">
        <div class="setting-row">
          <div><b>EF 初值</b><div class="list-sub">易记系数，默认 2.5</div></div>
          <input v-model.number="settings['sm2.ef_initial']" class="input" style="width: 110px" type="number" step="0.1" />
        </div>
        <div class="setting-row">
          <div><b>EF 下限</b><div class="list-sub">低于此值不再下降，默认 1.3</div></div>
          <input v-model.number="settings['sm2.ef_min']" class="input" style="width: 110px" type="number" step="0.1" />
        </div>
        <div class="setting-row">
          <div><b>间隔上限（天）</b><div class="list-sub">防止无限拉长，默认 90</div></div>
          <input v-model.number="settings['sm2.interval_cap_days']" class="input" style="width: 110px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>每日新题上限</b></div>
          <input v-model.number="settings['sm2.daily_new_limit']" class="input" style="width: 110px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>每日复习上限</b></div>
          <input v-model.number="settings['sm2.daily_review_limit']" class="input" style="width: 110px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>提前复习也推进排程</b><div class="list-sub">默认关闭：未到期题评熟悉/精通只记录不推进</div></div>
          <button class="switch" :class="{ on: settings['review.early_advances'] }" @click="settings['review.early_advances'] = !settings['review.early_advances']"></button>
        </div>
        <div class="setting-row">
          <div><b>连续通过自动移出错题本</b><div class="list-sub">连续 N 次熟悉/精通后自动移出，0 表示不自动</div></div>
          <input v-model.number="settings['mistake.auto_remove_streak']" class="input" style="width: 110px" type="number" />
        </div>
      </div>

      <div class="section-title">导入与去重</div>
      <div class="card">
        <div class="setting-row">
          <div><b>导入直接入库</b><div class="list-sub">关闭时文件导入先进待审区；知识条目始终走待审</div></div>
          <button class="switch" :class="{ on: settings['import.direct_to_active'] }" @click="settings['import.direct_to_active'] = !settings['import.direct_to_active']"></button>
        </div>
        <div class="setting-row">
          <div><b>手动新建先进入待审区</b><div class="list-sub">适合希望在入库前统一审核</div></div>
          <button class="switch" :class="{ on: settings['manual.new_to_pending'] }" @click="settings['manual.new_to_pending'] = !settings['manual.new_to_pending']"></button>
        </div>
        <div class="setting-row">
          <div><b>单次导入最大行数</b></div>
          <input v-model.number="settings['import.max_rows']" class="input" style="width: 130px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>单次导入最大字节数</b><div class="list-sub">默认 5MB</div></div>
          <input v-model.number="settings['import.max_bytes']" class="input" style="width: 150px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>SimHash 汉明距离阈值</b><div class="list-sub">≤ 阈值视为近似重复，默认 3</div></div>
          <input v-model.number="settings['dedupe.simhash_threshold']" class="input" style="width: 110px" type="number" />
        </div>
        <div class="setting-row">
          <div><b>爬虫单次最大文件数</b></div>
          <input v-model.number="settings['crawl.max_files_per_run']" class="input" style="width: 110px" type="number" />
        </div>
      </div>

      <div class="form-actions" style="margin-top: 14px">
        <button class="btn" :disabled="saving" @click="saveSettings">{{ saving ? '保存中…' : '保存设置' }}</button>
      </div>

      <div class="section-title" style="justify-content: space-between">
        <span>AI 能力（M3a / M3b）</span>
        <button class="btn ghost sm" @click="loadAIStatus">刷新状态</button>
      </div>
      <div class="card">
        <div class="setting-row">
          <div>
            <b>AI 状态</b>
            <div class="list-sub">OpenAI 兼容接口；未配置时 AI 按钮会提示未配置，人工质检始终可用</div>
          </div>
          <span class="tag" :class="aiStatus?.configured ? 'green' : 'gray'">
            {{ aiStatus?.configured ? '已配置' : '未配置' }}
          </span>
        </div>
        <template v-if="aiStatus">
          <div class="setting-row">
            <div>
              <b>模型 / 地址</b>
              <div class="list-sub mono">{{ aiStatus.model || '—' }}</div>
            </div>
            <span class="list-sub mono">{{ aiStatus.base_url || '—' }}</span>
          </div>
          <div class="setting-row">
            <div>
              <b>本月用量</b>
              <div class="list-sub">
                {{ aiStatus.usage.tokens.toLocaleString() }} tokens · {{ aiStatus.usage.calls }} 次调用 ·
                缓存命中 {{ aiStatus.usage.cache_hits }}
              </div>
            </div>
            <span class="tag gray">预算 {{ aiStatus.monthly_token_limit.toLocaleString() }} tokens</span>
          </div>
          <div v-if="aiStatus.prompt_versions.length" class="setting-row">
            <div>
              <b>Prompt 版本</b>
              <div class="list-sub">
                {{ aiStatus.prompt_versions.map((item) => `${item.name} ${item.version}`).join('、') }}
              </div>
            </div>
          </div>
        </template>
        <div class="list-sub" style="margin-top: 8px">
          配置方式：在 .env 或环境变量中设置 BAJIU_AI_BASE_URL / BAJIU_AI_API_KEY / BAJIU_AI_MODEL。
          Key 只从环境读取，不会显示在此页面。AI 失败时可在待审详情转人工质检。
        </div>
        <div class="list-sub" style="margin-top: 8px">
          M3a 增强：待审详情生成打标建议（应用后才写入建议元数据）；题目详情可做错题解析与答案润色（应用后才覆盖答案）。
          M3b：知识详情可 AI 出题（只进待审区）；仿真面试默认不发送作答原文，勾选同意后才会调用 AI 评分与复盘；
          周报告在 AI 不可用时自动降级为本地统计版。
        </div>
      </div>

      <div class="section-title">板块管理（岗位方向）</div>
      <div class="card" style="padding: 6px 16px">
        <div v-for="board in store.tree" :key="board.id" class="setting-row">
          <div>
            <b :style="{ color: board.id === store.boardId ? 'var(--teal-d)' : '' }">{{ board.name }}</b>
            <div class="list-sub">{{ board.question_count }} 题 · {{ board.knowledge_count }} 条知识</div>
          </div>
          <div style="display: flex; align-items: center; gap: 12px">
            <span v-if="board.id === store.boardId" class="tag teal">当前</span>
            <button v-if="board.id !== store.boardId" class="btn ghost sm" @click="store.setBoard(board.id)">切换</button>
          </div>
        </div>
      </div>

      <div class="section-title" style="justify-content: space-between">
        <span>规则打标</span>
        <button class="btn sm" @click="openRule()">+ 新增规则</button>
      </div>
      <div class="card" style="padding: 6px 10px">
        <div v-if="rulesLoading" class="empty">加载中…</div>
        <table v-else>
          <colgroup>
            <col style="width: 22%" />
            <col style="width: 9%" />
            <col style="width: 12%" />
            <col style="width: 22%" />
            <col style="width: 9%" />
            <col style="width: 9%" />
            <col style="width: 7%" />
            <col style="width: 10%" />
          </colgroup>
          <thead>
            <tr>
              <th>关键词</th>
              <th>匹配</th>
              <th>标签</th>
              <th>分类</th>
              <th>难度</th>
              <th>频率</th>
              <th>权重</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in rules" :key="rule.id">
              <td style="font-family: ui-monospace, monospace; font-size: 13px">{{ rule.keyword }}</td>
              <td><span class="tag gray">{{ rule.match_type === 'regex' ? '正则' : '包含' }}</span></td>
              <td>{{ rule.tag_name || '—' }}</td>
              <td style="font-size: 13px; color: var(--ink2)">{{ rule.category_path || '—' }}</td>
              <td>{{ rule.difficulty ?? '—' }}</td>
              <td><span class="tag" :class="frequencyTone(rule.frequency)">{{ frequencyText(rule.frequency) }}</span></td>
              <td class="num">{{ rule.weight }}</td>
              <td>
                <div style="display: flex; gap: 5px">
                  <button class="switch" :class="{ on: rule.enabled }" style="transform: scale(0.72); transform-origin: left center" @click="toggleRule(rule)"></button>
                  <button class="btn ghost sm" @click="openRule(rule)">编辑</button>
                  <button class="btn danger-ghost sm" @click="deleteRule(rule)">删</button>
                </div>
              </td>
            </tr>
            <tr v-if="!rules.length">
              <td colspan="8"><div class="empty">暂无规则</div></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="section-title">数据与备份</div>
      <div class="card">
        <div style="display: flex; gap: 10px; flex-wrap: wrap">
          <button class="btn ghost" @click="exportData('json')">导出 JSON</button>
          <button class="btn ghost" @click="exportData('md')">导出 Markdown</button>
          <button class="btn ghost" @click="backup">生成 SQLite 备份</button>
        </div>
        <div class="section-title" style="font-size: 14px">备份文件（保留最近 7 份）</div>
        <div v-if="backups.length">
          <div v-for="file in backups" :key="file.name" class="list-row">
            <div class="list-main">
              <div class="list-title mono">{{ file.name }}</div>
              <div class="list-sub">{{ Math.round(file.size / 1024) }} KB · {{ formatDateTime(file.modified_at) }}</div>
            </div>
          </div>
        </div>
        <div v-else class="list-sub">还没有备份文件</div>

        <div class="section-title" style="font-size: 14px">恢复备份</div>
        <div class="board-banner" style="background: var(--orange-bg); border-color: #f0cfc0">
          <b style="color: var(--orange)">谨慎操作</b>
          <span>恢复会覆盖当前数据库；系统会先自动生成一份 pre-restore 备份，完成后建议重启服务。</span>
        </div>
        <div class="toolbar">
          <input ref="restoreInput" type="file" accept=".db" @change="onRestoreChange" />
          <label style="display: flex; align-items: center; gap: 6px; font-size: 13.5px">
            <input v-model="restoreConfirm" type="checkbox" />
            我确认覆盖当前数据库
          </label>
          <button class="btn danger-ghost" :disabled="restoring || !restoreFile" @click="restore">
            {{ restoring ? '恢复中…' : '恢复备份' }}
          </button>
        </div>
      </div>

      <div class="section-title">账号</div>
      <div class="card">
        <div class="setting-row">
          <div><b>{{ store.user?.username || 'admin' }}</b><div class="list-sub">单用户本地部署 · 仅监听 127.0.0.1</div></div>
          <button class="btn ghost" @click="logout">退出登录</button>
        </div>
      </div>
    </template>

    <Modal :open="ruleOpen" :title="editingRuleId ? '编辑规则' : '新增规则'" @close="ruleOpen = false">
      <div class="form-grid">
        <div class="field full">
          <label>关键词 / 正则</label>
          <input v-model="ruleForm.keyword" class="input" placeholder="例如：三次握手 或 进程|线程" />
        </div>
        <div class="field">
          <label>匹配方式</label>
          <select v-model="ruleForm.match_type" class="select">
            <option value="contains">包含</option>
            <option value="regex">正则</option>
          </select>
        </div>
        <div class="field">
          <label>建议标签</label>
          <select v-model="ruleForm.tag_id" class="select">
            <option :value="null">不指定</option>
            <option v-for="tag in tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
          </select>
        </div>
        <div class="field full">
          <label>建议分类</label>
          <select v-model="ruleForm.category_id" class="select">
            <option :value="null">不指定</option>
            <option v-for="category in flatCategories" :key="category.id" :value="category.id">
              {{ category.path }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>建议难度</label>
          <select v-model="ruleForm.difficulty" class="select">
            <option value="">不指定</option>
            <option :value="1">1</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="4">4</option>
            <option :value="5">5</option>
          </select>
        </div>
        <div class="field">
          <label>建议频率</label>
          <select v-model="ruleForm.frequency" class="select">
            <option value="">不指定</option>
            <option value="high">高频</option>
            <option value="mid">中频</option>
            <option value="low">低频</option>
          </select>
        </div>
        <div class="field">
          <label>权重</label>
          <input v-model.number="ruleForm.weight" class="input" type="number" step="0.1" min="0.1" />
        </div>
        <div class="field">
          <label>启用</label>
          <button class="switch" :class="{ on: ruleForm.enabled }" style="margin-top: 6px" @click="ruleForm.enabled = !ruleForm.enabled"></button>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn ghost" @click="ruleOpen = false">取消</button>
        <button class="btn" :disabled="ruleSaving" @click="saveRule">{{ ruleSaving ? '保存中…' : '保存' }}</button>
      </div>
    </Modal>
  </div>
</template>
