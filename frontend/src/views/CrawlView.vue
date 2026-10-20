<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import type { CrawlSource, CrawlTask, CrawlTaskFile } from '../api/types'
import Modal from '../components/Modal.vue'
import { useAppStore } from '../stores/app'
import {
  formatDateTime,
  sourceText,
  taskStatusText,
  taskStatusTone,
} from '../utils/labels'

const store = useAppStore()

const sources = ref<CrawlSource[]>([])
const tasks = ref<CrawlTask[]>([])
const sourcesLoading = ref(true)
const tasksLoading = ref(true)

const sourceFormOpen = ref(false)
const editingSourceId = ref<number | null>(null)
const sourceSaving = ref(false)
const sourceForm = reactive({
  name: '',
  source_kind: 'github' as 'github' | 'nowcoder',
  url: '',
  enabled: true,
  user_agent: 'InterviewReviewBot/1.0 (+personal use)',
  interval_sec: 10,
  timeout_sec: 15,
  max_retries: 3,
  max_files_per_run: 100,
})

const detailOpen = ref(false)
const taskDetail = ref<CrawlTask | null>(null)
const taskFiles = ref<CrawlTaskFile[]>([])

let pollTimer: number | null = null

async function loadSources(): Promise<void> {
  sourcesLoading.value = true
  try {
    sources.value = await api.get<CrawlSource[]>('/crawl/sources')
  } catch (err: any) {
    store.toast(err?.message || '爬虫源加载失败', 'error')
  } finally {
    sourcesLoading.value = false
  }
}

async function loadTasks(): Promise<void> {
  tasksLoading.value = true
  try {
    const data = await api.get<{ items: CrawlTask[] }>('/crawl/tasks?page_size=30')
    tasks.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '任务列表加载失败', 'error')
  } finally {
    tasksLoading.value = false
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = window.setInterval(async () => {
    await loadTasks()
    const busy = tasks.value.some((task) => task.status === 'pending' || task.status === 'running')
    if (!busy) stopPolling()
  }, 3000)
}

function stopPolling(): void {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function runSource(source: CrawlSource): Promise<void> {
  if (!['github', 'nowcoder'].includes(source.source_kind)) {
    store.toast('该源类型暂不支持采集', 'info')
    return
  }
  try {
    await api.post(`/crawl/sources/${source.id}/run`)
    store.toast('任务已提交，正在后台采集', 'success')
    await loadTasks()
    startPolling()
  } catch (err: any) {
    store.toast(err?.message || '触发采集失败', 'error')
  }
}

function openSourceForm(source?: CrawlSource): void {
  if (source) {
    editingSourceId.value = source.id
    sourceForm.name = source.name
    sourceForm.source_kind = source.source_kind === 'nowcoder' ? 'nowcoder' : 'github'
    sourceForm.url = source.url
    sourceForm.enabled = source.enabled
    sourceForm.user_agent = source.user_agent
    sourceForm.interval_sec = source.interval_sec
    sourceForm.timeout_sec = source.timeout_sec
    sourceForm.max_retries = source.max_retries
    sourceForm.max_files_per_run = source.max_files_per_run
  } else {
    editingSourceId.value = null
    sourceForm.name = ''
    sourceForm.source_kind = 'github'
    sourceForm.url = 'https://github.com/'
    sourceForm.enabled = true
    sourceForm.user_agent = 'InterviewReviewBot/1.0 (+personal use)'
    sourceForm.interval_sec = 10
    sourceForm.timeout_sec = 15
    sourceForm.max_retries = 3
    sourceForm.max_files_per_run = 100
  }
  sourceFormOpen.value = true
}

function changeSourceKind(): void {
  if (sourceForm.source_kind === 'nowcoder') {
    sourceForm.url = 'https://www.nowcoder.com/'
    sourceForm.interval_sec = 5
    sourceForm.timeout_sec = 30
    sourceForm.max_retries = 2
  } else {
    sourceForm.url = 'https://github.com/'
    sourceForm.interval_sec = 10
    sourceForm.timeout_sec = 15
    sourceForm.max_retries = 3
  }
}

async function saveSource(): Promise<void> {
  if (!sourceForm.name.trim() || !sourceForm.url.trim()) {
    store.toast('名称和 URL 不能为空', 'error')
    return
  }
  sourceSaving.value = true
  const { source_kind, ...rest } = sourceForm
  const payload = { ...rest, name: sourceForm.name.trim(), url: sourceForm.url.trim() }
  try {
    if (editingSourceId.value) {
      await api.patch(`/crawl/sources/${editingSourceId.value}`, payload)
      store.toast('源配置已保存', 'success')
    } else {
      await api.post('/crawl/sources', { ...payload, source_kind })
      store.toast('源已创建', 'success')
    }
    sourceFormOpen.value = false
    await loadSources()
  } catch (err: any) {
    store.toast(err?.message || '保存失败', 'error')
  } finally {
    sourceSaving.value = false
  }
}

async function deleteSource(source: CrawlSource): Promise<void> {
  if (!window.confirm(`删除源「${source.name}」？相关任务与来源记录会一并删除，无来源内容归档。`)) return
  try {
    const data = await api.delete<any>(`/crawl/sources/${source.id}`)
    store.toast(
      `源已删除，归档题目 ${data.archived_questions}、知识 ${data.archived_knowledge}`,
      'success',
    )
    await Promise.all([loadSources(), loadTasks(), store.loadBadges()])
  } catch (err: any) {
    store.toast(err?.message || '删除失败', 'error')
  }
}

async function openTask(task: CrawlTask): Promise<void> {
  try {
    const data = await api.get<{ task: CrawlTask; files: CrawlTaskFile[] }>(`/crawl/tasks/${task.id}`)
    taskDetail.value = data.task
    taskFiles.value = data.files
    detailOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '任务详情加载失败', 'error')
  }
}

async function retryTask(task: CrawlTask): Promise<void> {
  try {
    await api.post(`/crawl/tasks/${task.id}/retry`)
    store.toast('已创建重试任务，仅处理失败文件', 'success')
    await loadTasks()
    startPolling()
  } catch (err: any) {
    store.toast(err?.message || '重试失败', 'error')
  }
}

function sourceName(id: number): string {
  return sources.value.find((source) => source.id === id)?.name || `源 #${id}`
}

onMounted(async () => {
  await Promise.all([loadSources(), loadTasks()])
  if (tasks.value.some((task) => task.status === 'running' || task.status === 'pending')) startPolling()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div>
    <div class="toolbar">
      <span class="tag teal">M2 · GitHub + 牛客公开页</span>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" @click="loadSources(); loadTasks()">刷新</button>
      <button class="btn" @click="openSourceForm()">+ 新增源</button>
    </div>

    <div class="section-title">爬虫源</div>
    <div v-if="sourcesLoading" class="card empty">加载中…</div>
    <div v-else class="grid" style="grid-template-columns: repeat(2, 1fr)">
      <div v-for="source in sources" :key="source.id" class="card source-card">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px">
          <b>{{ source.name }}</b>
          <span class="tag" :class="source.enabled ? 'green' : 'gray'">
            {{ source.enabled ? '启用' : '停用' }}
          </span>
        </div>
        <div class="mono" style="color: var(--ink3)">{{ source.url }}</div>
        <div style="font-size: 13.5px; color: var(--ink2)">
          类型 {{ source.source_kind === 'nowcoder' ? '牛客' : 'GitHub' }} · 间隔 {{ source.interval_sec }}s · 单次最多
          {{ source.max_files_per_run }} 文件 · 上次 {{ formatDateTime(source.last_run_at) }}
        </div>
        <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap">
          <button class="btn sm" :disabled="!['github', 'nowcoder'].includes(source.source_kind)" @click="runSource(source)">
            立即采集
          </button>
          <button class="btn ghost sm" @click="openSourceForm(source)">配置</button>
          <button class="btn danger-ghost sm" @click="deleteSource(source)">删除</button>
        </div>
      </div>
      <div v-if="!sources.length" class="card empty">还没有爬虫源</div>
    </div>

    <div class="section-title">采集任务</div>
    <div class="card" style="padding: 6px 10px">
      <div v-if="tasksLoading" class="empty">加载中…</div>
      <table v-else>
        <colgroup>
          <col style="width: 8%" />
          <col style="width: 24%" />
          <col style="width: 11%" />
          <col style="width: 17%" />
          <col style="width: 18%" />
          <col style="width: 22%" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>源</th>
            <th>状态</th>
            <th>文件（成功/失败/总数）</th>
            <th>时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td class="num">#{{ task.id }}</td>
            <td>{{ sourceName(task.source_id) }}</td>
            <td>
              <span class="tag" :class="taskStatusTone(task.status)">{{ taskStatusText(task.status) }}</span>
            </td>
            <td class="num">
              <span style="color: var(--green)">{{ task.success_files }}</span> /
              <span style="color: var(--orange)">{{ task.failed_files }}</span> /
              {{ task.total_files }}
            </td>
            <td style="font-size: 13px; color: var(--ink2)">{{ formatDateTime(task.created_at) }}</td>
            <td>
              <div style="display: flex; gap: 6px">
                <button class="btn ghost sm" @click="openTask(task)">详情</button>
                <button
                  class="btn ghost sm"
                  :disabled="!task.failed_files"
                  @click="retryTask(task)"
                >
                  重试失败
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!tasks.length">
            <td colspan="6"><div class="empty">还没有采集任务</div></td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal :open="sourceFormOpen" :title="editingSourceId ? '编辑爬虫源' : '新增采集源'" @close="sourceFormOpen = false">
      <div class="form-grid">
        <div class="field full">
          <label>来源类型</label>
          <select
            v-model="sourceForm.source_kind"
            class="select"
            :disabled="!!editingSourceId"
            @change="changeSourceKind"
          >
            <option value="github">GitHub 仓库 / 目录 / raw Markdown</option>
            <option value="nowcoder">牛客公开帖子 / sitemap</option>
          </select>
          <span class="hint">牛客仅采集公开页面，遵守 robots.txt 与请求间隔；不支持登录态/付费内容。</span>
        </div>
        <div class="field full">
          <label>名称</label>
          <input v-model="sourceForm.name" class="input" placeholder="GitHub · CS-Notes 面经仓库" />
        </div>
        <div class="field full">
          <label>{{ sourceForm.source_kind === 'nowcoder' ? '帖子 / sitemap URL' : '仓库 / 目录 / raw URL' }}</label>
          <input
            v-model="sourceForm.url"
            class="input"
            :placeholder="sourceForm.source_kind === 'nowcoder'
              ? 'https://www.nowcoder.com/discuss/123 或 /sitemap1.xml'
              : 'https://github.com/owner/repo 或 /tree/main/docs'"
          />
          <span v-if="sourceForm.source_kind === 'nowcoder'" class="hint">
            支持单个公开帖子或站点 sitemap（sitemap 会批量列出公开帖子）；列表页为动态渲染，不支持直接配置。
          </span>
          <span v-else class="hint">仅允许 github.com / raw.githubusercontent.com；支持可选 GITHUB_TOKEN 环境变量。</span>
        </div>
        <div class="field full">
          <label>请求 User-Agent</label>
          <input v-model="sourceForm.user_agent" class="input" />
          <span class="hint">建议标明用途；GitHub API 限流时还可配置 GITHUB_TOKEN。</span>
        </div>
        <div class="field">
          <label>请求间隔（秒）</label>
          <input v-model.number="sourceForm.interval_sec" class="input" type="number" min="1" />
        </div>
        <div class="field">
          <label>超时（秒）</label>
          <input v-model.number="sourceForm.timeout_sec" class="input" type="number" min="1" />
        </div>
        <div class="field">
          <label>失败重试次数</label>
          <input v-model.number="sourceForm.max_retries" class="input" type="number" min="1" />
        </div>
        <div class="field">
          <label>单次最大文件数</label>
          <input v-model.number="sourceForm.max_files_per_run" class="input" type="number" min="1" />
        </div>
        <div class="field full">
          <label style="display: flex; align-items: center; gap: 8px">
            <button class="switch" :class="{ on: sourceForm.enabled }" type="button" @click="sourceForm.enabled = !sourceForm.enabled"></button>
            启用该源
          </label>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn ghost" @click="sourceFormOpen = false">取消</button>
        <button class="btn" :disabled="sourceSaving" @click="saveSource">{{ sourceSaving ? '保存中…' : '保存' }}</button>
      </div>
    </Modal>

    <Modal :open="detailOpen" title="采集任务详情" wide @close="detailOpen = false">
      <template v-if="taskDetail">
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px">
          <b>任务 #{{ taskDetail.id }}</b>
          <span class="tag" :class="taskStatusTone(taskDetail.status)">{{ taskStatusText(taskDetail.status) }}</span>
          <span class="tag gray">尝试 {{ taskDetail.attempt }}</span>
          <span class="tag gray">成功 {{ taskDetail.success_files }}</span>
          <span class="tag orange">失败 {{ taskDetail.failed_files }}</span>
          <span class="tag gray">总文件 {{ taskDetail.total_files }}</span>
        </div>
        <div class="section-title" style="font-size: 14px">任务日志</div>
        <div class="log-box">{{ taskDetail.log || '暂无日志' }}</div>
        <div class="section-title" style="font-size: 14px">逐文件状态</div>
        <div style="max-height: 340px; overflow-y: auto">
          <table>
            <colgroup>
              <col style="width: 8%" />
              <col style="width: 44%" />
              <col style="width: 10%" />
              <col style="width: 9%" />
              <col style="width: 9%" />
              <col style="width: 20%" />
            </colgroup>
            <thead>
              <tr>
                <th>状态</th>
                <th>URL</th>
                <th>HTTP</th>
                <th>解析</th>
                <th>重试</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="file in taskFiles" :key="file.id">
                <td><span class="tag" :class="taskStatusTone(file.status)">{{ taskStatusText(file.status) }}</span></td>
                <td class="mono">{{ file.url }}</td>
                <td class="num">{{ file.http_status ?? '—' }}</td>
                <td class="num">{{ file.parsed_count }}</td>
                <td></td>
                <td style="color: var(--orange); font-size: 12.5px">{{ file.error || '—' }}</td>
              </tr>
              <tr v-if="!taskFiles.length">
                <td colspan="6"><div class="empty">暂无文件记录</div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </Modal>
  </div>
</template>
