import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = process.env.BAJIU_BASE || 'http://127.0.0.1:8000'
const EDGE =
  process.env.EDGE_PATH ||
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'

/**
 * BAJIU_SEGMENT：full（默认）| dashboard | m3a | m3b。
 * 非 full 时复用浏览器上下文里的已有 token，只跑指定片段，便于定位失败点。
 */
const SEGMENT = process.env.BAJIU_SEGMENT || 'full'

const here = path.dirname(fileURLToPath(import.meta.url))
const artifacts = path.join(here, 'artifacts')
await mkdir(artifacts, { recursive: true })

const browser = await chromium.launch({ executablePath: EDGE, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })

const problems = []
page.on('console', (message) => {
  if (message.type() === 'error') problems.push(`console: ${message.text()}`)
})
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))

async function nav(name) {
  await page.locator('.nav-item', { hasText: name }).click()
  await page.waitForTimeout(500)
}

async function createTempPending() {
  const ids = await page.evaluate(async () => {
    const token = localStorage.getItem('bajiu_token')
    const created = []
    for (const index of [1, 2]) {
      const response = await fetch('/api/v1/knowledge', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: `E2E 待审条目 ${Date.now()}-${index}`,
          content: '用于端到端冒烟测试的临时知识条目，测试结束后自动拒绝。',
          send_to_pending: true,
        }),
      })
      const payload = await response.json()
      if (payload?.data?.item?.id) created.push(payload.data.item.id)
    }
    return created
  })
  return ids
}

async function rejectPending(ids) {
  for (const id of ids || []) {
    await page.evaluate(async (itemId) => {
      const token = localStorage.getItem('bajiu_token')
      await fetch(`/api/v1/pending/${itemId}/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ reviewer_note: 'E2E 自动清理' }),
      })
    }, id)
  }
}

async function apiTotal(url) {
  return page.evaluate(async (target) => {
    const token = localStorage.getItem('bajiu_token')
    const response = await fetch(target, { headers: { Authorization: `Bearer ${token}` } })
    const payload = await response.json()
    return payload?.data?.total ?? 0
  }, url)
}

/** 在页面上下文里直接调接口，返回完整响应体；用于准备/清理 E2E 数据。 */
async function apiCall(method, url, body) {
  return page.evaluate(
    async ({ method: verb, url: target, body: payload }) => {
      const token = localStorage.getItem('bajiu_token')
      const response = await fetch(target, {
        method: verb,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      })
      return response.json()
    },
    { method, url, body },
  )
}

async function waitQuestionRows(expected) {
  await page.waitForFunction(
    (count) => {
      if (document.querySelector('#main .card.empty')) return false
      const rows = document.querySelectorAll('#main table tbody tr')
      return rows.length === Math.min(count, 20)
    },
    expected,
    { timeout: 10000 },
  )
}

async function enterApp() {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  if (SEGMENT !== 'full') {
    const token = await page.evaluate(() => localStorage.getItem('bajiu_token'))
    if (token) {
      await page.goto(`${BASE}/#/dashboard`, { waitUntil: 'networkidle' })
      await page.waitForSelector('.board-banner', { timeout: 15000 })
      return
    }
    // 全新浏览器上下文没有 token：走一次正常登录。
  }
  await page.waitForSelector('#username', { timeout: 15000 })
  await page.screenshot({ path: path.join(artifacts, '01-login.png'), fullPage: true })
  await page.getByRole('button', { name: '进入系统' }).click()
  await page.waitForSelector('.board-banner', { timeout: 15000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(artifacts, '02-dashboard.png'), fullPage: true })
}

const summary = {}

async function runDashboardSegment() {
  const dashboardText = await page.locator('#main').innerText()
  if (!dashboardText.includes('今日到期')) throw new Error('仪表盘缺少今日到期指标')

  await nav('主动刷题')
  await page.waitForSelector('.pcard', { timeout: 10000 })
  summary.practiceStem = await page.locator('.p-stem').first().innerText()
  await page.getByRole('button', { name: '显示答案' }).click()
  await page.waitForSelector('.panswer', { timeout: 10000 })
  const answerText = await page.locator('.panswer').innerText()
  if (!answerText.includes('参考答案')) throw new Error('刷题答案未展示')
  await page.screenshot({ path: path.join(artifacts, '03-practice.png'), fullPage: true })

  await nav('今日复习')
  await page.waitForTimeout(700)
  const reviewText = await page.locator('#main').innerText()
  if (!reviewText.includes('到期')) throw new Error('复习页缺少到期队列')

  await nav('题库管理')
  await page.waitForSelector('table tbody tr', { timeout: 10000 })
  await page.locator('table tbody tr').first().getByRole('button', { name: '详情' }).click()
  await page.waitForSelector('.modal-card', { timeout: 10000 })
  const detailText = await page.locator('.modal-card').innerText()
  if (!detailText.includes('参考答案')) throw new Error('题库详情缺少参考答案')
  await page.screenshot({ path: path.join(artifacts, '04-library-detail.png'), fullPage: true })
  await page.locator('.modal-close').click()

  // 多维筛选：难度多选（维度内 OR）→ 行数与行内容 → 重置恢复
  const difficultyCounts = {}
  for (const value of ['1', '2', '3', '4', '5']) {
    difficultyCounts[value] = await apiTotal(
      `/api/v1/questions?status=active&difficulties=${value}&page=1&page_size=20`,
    )
  }
  const activeDifficulties = Object.keys(difficultyCounts).filter(
    (value) => difficultyCounts[value] > 0,
  )
  if (activeDifficulties.length < 2) throw new Error('题库缺少可用于多选筛选的难度数据')
  const allTotal = await apiTotal('/api/v1/questions?status=active&page=1&page_size=20')
  const difficultyLabels = { 1: '1 入门', 2: '2', 3: '3', 4: '4', 5: '5 困难' }
  const [firstDifficulty, secondDifficulty] = activeDifficulties.slice(0, 2)
  const firstLabel = difficultyLabels[firstDifficulty]
  const secondLabel = difficultyLabels[secondDifficulty]
  const multiExpectedTotal = await apiTotal(
    `/api/v1/questions?status=active&difficulties=${firstDifficulty},${secondDifficulty}&page=1&page_size=20`,
  )

  const difficultyMulti = page.locator('.multi-select').first()
  await difficultyMulti.locator('.multi-trigger').click()
  const difficultyOption = (label) =>
    difficultyMulti.locator('.multi-option').filter({ hasText: label }).first()
  await difficultyOption(firstLabel).locator('input').check()
  await waitQuestionRows(difficultyCounts[firstDifficulty])
  const singleFilterTitles = await page
    .locator('#main table tbody tr .difficulty-bars')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('title')))
  if (singleFilterTitles.some((title) => title !== `难度 ${firstDifficulty}/5`)) {
    throw new Error(`单选难度后出现不匹配行：${singleFilterTitles.join(', ')}`)
  }
  await difficultyOption(secondLabel).locator('input').check()
  await waitQuestionRows(multiExpectedTotal)
  const multiSummary = await difficultyMulti.locator('.multi-trigger').innerText()
  if (!multiSummary.includes(firstLabel) || !multiSummary.includes(secondLabel)) {
    throw new Error(`多选摘要未显示两个难度：${multiSummary}`)
  }
  const multiFilterTitles = await page
    .locator('#main table tbody tr .difficulty-bars')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('title')))
  const allowedTitles = [`难度 ${firstDifficulty}/5`, `难度 ${secondDifficulty}/5`]
  if (multiFilterTitles.some((title) => !allowedTitles.includes(title))) {
    throw new Error(`多选难度后出现不匹配行：${multiFilterTitles.join(', ')}`)
  }
  await page.getByRole('button', { name: '重置' }).click()
  await waitQuestionRows(allTotal)
  if (allTotal > 20) {
    const paginationText = await page.locator('.pagination').innerText()
    if (!paginationText.includes(`共 ${allTotal} 条`)) throw new Error('重置后未恢复全部题目')
  }
  await page.screenshot({ path: path.join(artifacts, '09-library-multiselect.png'), fullPage: true })
  summary.filters = {
    allTotal,
    difficulties: [firstDifficulty, secondDifficulty],
    firstCount: difficultyCounts[firstDifficulty],
    multiCount: multiExpectedTotal,
  }

  await nav('知识库')
  await page.waitForSelector('table tbody tr', { timeout: 10000 })
  const knowledgeText = await page.locator('#main').innerText()
  if (!knowledgeText.includes('知识条目')) throw new Error('知识库页未渲染')

  await nav('本地导入')
  await page.waitForSelector('.import-drop', { timeout: 10000 })

  await nav('采集任务')
  await page.waitForSelector('.source-card', { timeout: 10000 })

  await nav('采集待审')
  await page.waitForTimeout(800)
  let tempPendingIds = []
  if (!(await page.locator('.pend-item').count())) {
    tempPendingIds = await createTempPending()
    await page.reload({ waitUntil: 'networkidle' })
  }
  await page.waitForSelector('.pend-item', { timeout: 10000 })
  const pendingCount = await page.locator('.pend-item').count()
  if (pendingCount < 1) throw new Error('待审队列为空')
  // 批量通过只在前端选择、不提交，避免改变演示数据；单测已覆盖接口行为。
  const bulkButton = page.getByRole('button', { name: /批量通过/ })
  const selectedCount = async () => Number((await bulkButton.innerText()).match(/（(\d+)）/)?.[1] ?? -1)
  const bulkDisabledBefore = await bulkButton.isDisabled()
  await page.locator('.pend-item input[type="checkbox"]').first().check()
  const countAfterSelect = await selectedCount()
  await page.getByLabel('全选本页').check()
  const countAfterSelectAll = await selectedCount()
  await page.locator('.pend-item input[type="checkbox"]').nth(1).uncheck()
  const countAfterUnselect = await selectedCount()
  await page.getByLabel('全选本页').uncheck()
  if (!bulkDisabledBefore) throw new Error('批量通过按钮在未选择时应禁用')
  if (countAfterSelect !== 1) throw new Error(`单选后数量应为 1，实际 ${countAfterSelect}`)
  if (countAfterSelectAll !== pendingCount) throw new Error(`全选后数量应为 ${pendingCount}，实际 ${countAfterSelectAll}`)
  if (countAfterUnselect !== pendingCount - 1) throw new Error('取消一项后数量未减 1')
  await page.screenshot({ path: path.join(artifacts, '07-pending-bulk.png'), fullPage: true })
  summary.bulk = {
    pendingCount,
    disabledBeforeSelect: bulkDisabledBefore,
    countAfterSelect,
    countAfterSelectAll,
    countAfterUnselect,
  }

  // 人工质检通道：AI 未配置时也必须完整可用
  await page.locator('.pend-item').first().getByRole('button', { name: '详情' }).click()
  await page.waitForSelector('.modal-card .quality-panel', { timeout: 10000 })
  await page.locator('.quality-panel').getByRole('button', { name: '人工质检' }).click()
  await page.waitForSelector('.quality-manual-form', { timeout: 10000 })
  await page
    .locator('.quality-manual-form textarea')
    .first()
    .fill('E2E 人工质检：内容完整，未发现事实错误。')
  await page.locator('.quality-manual-form select').nth(1).selectOption('high')
  await page.getByRole('button', { name: '保存人工质检' }).click()
  await page.waitForSelector('.quality-panel .quality-issue', { timeout: 10000 })
  const qualityText = await page.locator('.quality-panel').innerText()
  if (!qualityText.includes('人工') || !qualityText.includes('高风险')) {
    throw new Error(`人工质检结果未正确展示：${qualityText}`)
  }
  await page.screenshot({ path: path.join(artifacts, '10-quality-manual.png'), fullPage: true })
  await page.locator('.modal-card .modal-close').last().click()
  await page.waitForTimeout(500)
  if (!(await page.locator('.pend-item', { hasText: '质检' }).count())) {
    throw new Error('待审列表未显示质检徽标')
  }

  await rejectPending(tempPendingIds)

  await nav('统计复盘')
  await page.waitForSelector('.chart-svg', { timeout: 10000 })
  await page.waitForSelector('.heatmap', { timeout: 10000 })

  await nav('知识图谱')
  await page.waitForSelector('.graph-node', { timeout: 10000 })
  const graphNodeCount = await page.locator('.graph-node').count()
  if (!graphNodeCount) throw new Error('知识图谱没有节点')
  await page.locator('.graph-node').first().click()
  await page.waitForSelector('.graph-side .tag.teal', { timeout: 5000 })
  const nodeSideText = await page.locator('.graph-side').innerText()
  if (!nodeSideText.includes('知识条目')) throw new Error('点击节点后侧栏未显示知识详情')
  if (!nodeSideText.includes('以此为中心')) throw new Error('节点侧栏缺少聚焦按钮')
  await page.screenshot({ path: path.join(artifacts, '08-graph-node.png'), fullPage: true })

  await page.getByRole('button', { name: '以此为中心' }).click()
  await page.waitForSelector('button:has-text("取消聚焦")', { timeout: 10000 })
  await page.waitForTimeout(300)
  await page.waitForFunction(
    () =>
      !document.querySelector('#main .card.empty') &&
      document.querySelectorAll('#main .graph-node').length > 0,
    { timeout: 10000 },
  )
  await page.getByRole('button', { name: '取消聚焦' }).click()
  await page.waitForTimeout(300)
  await page.waitForFunction(
    () =>
      !document.querySelector('#main .card.empty') &&
      document.querySelectorAll('#main .graph-node').length > 0,
    { timeout: 10000 },
  )

  await page.getByLabel('显示题目节点').check()
  await page.waitForFunction(
    () => {
      const title = document.querySelector('#main .section-title')?.textContent || ''
      const match = title.match(/\/\s*(\d+)\s*题/)
      return match ? Number(match[1]) > 0 : false
    },
    { timeout: 10000 },
  )
  const graphText = await page.locator('#main').innerText()
  if (!graphText.includes('知识图谱')) throw new Error('知识图谱页未渲染')
  await page.screenshot({ path: path.join(artifacts, '08-graph.png'), fullPage: true })
  summary.graph = { nodeCount: graphNodeCount }

  await nav('设置')
  await page.waitForTimeout(700)
  const settingsText = await page.locator('#main').innerText()
  if (!settingsText.includes('SM-2 间隔重复参数')) throw new Error('设置页未渲染')
  if (!settingsText.includes('AI 能力（M3a / M3b）')) throw new Error('设置页缺少 AI 状态')
  if (!settingsText.includes('BAJIU_AI_BASE_URL')) throw new Error('设置页缺少 AI 配置说明')
  await page.screenshot({ path: path.join(artifacts, '05-settings.png'), fullPage: true })

  await nav('收藏夹')
  await page.waitForTimeout(500)
  await nav('错题本')
  await page.waitForTimeout(500)
  const mistakeExport = page.getByRole('button', { name: '导出 Markdown' })
  const downloadPromise = page.waitForEvent('download', { timeout: 5000 }).catch(() => null)
  if (await mistakeExport.isEnabled()) {
    await mistakeExport.click()
    const download = await downloadPromise
    if (!download) throw new Error('错题本 Markdown 导出未触发下载')
  }
  await nav('考前冲刺')
  await page.waitForSelector('.board-banner', { timeout: 10000 })
}

async function runM3aSegment() {
  // M3a：待审详情的 AI 打标建议面板；未配置 AI 时给出确切原因，人工通道不受影响。
  const pending = (await apiCall('GET', '/api/v1/pending?status=pending&page_size=1'))?.data?.items?.[0]
  if (pending) {
    await nav('采集待审')
    await page.waitForSelector('.pend-item', { timeout: 10000 })
    await page
      .locator('.pend-item', { hasText: pending.stem || pending.knowledge_title || '' })
      .first()
      .getByRole('button', { name: '详情' })
      .click()
    await page.waitForSelector('.modal-card .ai-suggest-panel', { timeout: 10000 })
    const panelText = await page.locator('.ai-suggest-panel').innerText()
    if (!panelText.includes('AI 打标建议')) throw new Error('待审详情缺少 AI 打标建议面板')
    const aiConfigured = await page.evaluate(async () => {
      const token = localStorage.getItem('bajiu_token')
      const response = await fetch('/api/v1/ai/status', {
        headers: { Authorization: `Bearer ${token}` },
      })
      return (await response.json())?.data?.configured === true
    })
    if (!aiConfigured) {
      await page.locator('.ai-suggest-panel').getByRole('button', { name: '生成打标建议' }).click()
      await page.waitForSelector('.ai-suggest-failed', { timeout: 15000 })
      const failedText = await page.locator('.ai-suggest-panel').innerText()
      if (!failedText.includes('未配置 AI')) throw new Error(`未配置 AI 时未给出降级提示：${failedText}`)
    }
    await page.screenshot({ path: path.join(artifacts, '11-ai-tagging.png'), fullPage: true })
    await page.locator('.modal-card .modal-close').last().click()
    await page.waitForTimeout(300)
  }

  // 题目详情包含答案润色与错题解析面板（只渲染入口，不调用 AI）。
  await nav('题库管理')
  await page.waitForSelector('table tbody tr', { timeout: 10000 })
  await page.locator('table tbody tr').first().getByRole('button', { name: '详情' }).click()
  await page.waitForSelector('.modal-card .ai-suggest-panel', { timeout: 10000 })
  const libraryAiText = await page.locator('.modal-card').innerText()
  if (!libraryAiText.includes('AI 答案润色') || !libraryAiText.includes('AI 错题解析')) {
    throw new Error('题目详情缺少答案润色/错题解析入口')
  }
  await page.locator('.modal-card .modal-close').click()
}

async function runM3bSegment() {
  // M3b：仿真面试（不勾选 AI 同意，全程本地评分，报告走基础版）。
  const total = (await apiCall('GET', '/api/v1/questions?status=active&page_size=1'))?.data?.total ?? 0
  if (!total) throw new Error('题库为空，无法进行面试冒烟')
  await nav('仿真面试')
  await page.getByRole('button', { name: '+ 开始仿真面试' }).click()
  await page.waitForSelector('.modal-card', { timeout: 10000 })
  await page.locator('.modal-card select').first().selectOption('3')
  await page.locator('.modal-card').getByRole('button', { name: '随机组卷并开始' }).click()
  await page.waitForSelector('.iv-main .iv-stem', { timeout: 15000 })
  const ivQuestion = await page.locator('.iv-main .iv-stem').innerText()
  if (!ivQuestion.trim()) throw new Error('面试题干为空')
  await page
    .locator('.iv-main textarea.iv-answer')
    .first()
    .fill('E2E 作答：先给结论，再讲原理与边界条件。')
  await page.locator('.iv-main').getByRole('button', { name: '提交作答' }).click()
  // 提交后停留在当前题展示评分与追问，再手动进入下一题。
  await page.waitForSelector('.iv-main .iv-answer-readonly', { timeout: 15000 })
  await page.locator('.iv-main .iv-score-row select').selectOption('4')
  await page.locator('.iv-main').getByRole('button', { name: '保存评分' }).click()
  await page.waitForSelector('.iv-main .iv-score-row .tag.green', { timeout: 10000 })
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: '结束面试并生成报告' }).click()
  await page.waitForSelector('.iv-report-head', { timeout: 30000 })
  const reportText = await page.locator('.modal-card').innerText()
  if (!reportText.includes('面试复盘报告') || !reportText.includes('80')) {
    throw new Error(`面试报告未正确渲染：${reportText.slice(0, 200)}`)
  }
  await page.screenshot({ path: path.join(artifacts, '12-interview-report.png'), fullPage: true })
  await page.locator('.modal-card .modal-close').last().click()
  await page.waitForTimeout(500)
  if (!(await page.locator('#main .list-row').count())) {
    throw new Error('面试结束后历史记录未刷新')
  }

  // M3b：周报告基础版（AI 不可用时也必须有内容）。
  await nav('周学习报告')
  await page.waitForTimeout(600)
  await page.locator('.weekly-page select').first().selectOption('basic')
  await page.locator('.weekly-page').getByRole('button', { name: '生成本周报告' }).click()
  await page.waitForSelector('.weekly-main .weekly-summary', { timeout: 20000 })
  const weeklyText = await page.locator('.weekly-main').innerText()
  if (!weeklyText.includes('学习周报') || !weeklyText.includes('下周计划')) {
    throw new Error(`周报告内容不完整：${weeklyText.slice(0, 200)}`)
  }
  if (!(await page.locator('.weekly-list-item').count())) {
    throw new Error('周报告历史列表为空')
  }
  await page.screenshot({ path: path.join(artifacts, '13-weekly.png'), fullPage: true })
}

try {
  await enterApp()
  if (SEGMENT === 'full' || SEGMENT === 'dashboard') await runDashboardSegment()
  if (SEGMENT === 'full' || SEGMENT === 'm3a') await runM3aSegment()
  if (SEGMENT === 'full' || SEGMENT === 'm3b') await runM3bSegment()

  console.log(JSON.stringify({ ok: true, segment: SEGMENT, ...summary, problems }, null, 2))
  if (problems.length) process.exitCode = 1
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true })
  console.error('SMOKE FAILED:', error)
  console.error('problems:', problems)
  process.exitCode = 1
} finally {
  await browser.close()
}