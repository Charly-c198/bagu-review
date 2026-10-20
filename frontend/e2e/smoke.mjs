import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = process.env.BAJIU_BASE || 'http://127.0.0.1:8000'
const EDGE =
  process.env.EDGE_PATH ||
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'

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

try {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForSelector('#username', { timeout: 15000 })
  await page.screenshot({ path: path.join(artifacts, '01-login.png'), fullPage: true })

  await page.getByRole('button', { name: '进入系统' }).click()
  await page.waitForSelector('.board-banner', { timeout: 15000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(artifacts, '02-dashboard.png'), fullPage: true })

  const dashboardText = await page.locator('#main').innerText()
  if (!dashboardText.includes('今日到期')) throw new Error('仪表盘缺少今日到期指标')

  await nav('主动刷题')
  await page.waitForSelector('.pcard', { timeout: 10000 })
  const practiceStem = await page.locator('.p-stem').first().innerText()
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

  await nav('知识库')
  await page.waitForSelector('table tbody tr', { timeout: 10000 })
  const knowledgeText = await page.locator('#main').innerText()
  if (!knowledgeText.includes('知识条目')) throw new Error('知识库页未渲染')

  await nav('本地导入')
  await page.waitForSelector('.import-drop', { timeout: 10000 })

  await nav('采集任务')
  await page.waitForSelector('.source-card', { timeout: 10000 })

  await nav('采集待审')
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

  await nav('统计复盘')
  await page.waitForSelector('.chart-svg', { timeout: 10000 })

  await nav('设置')
  await page.waitForTimeout(700)
  const settingsText = await page.locator('#main').innerText()
  if (!settingsText.includes('SM-2 间隔重复参数')) throw new Error('设置页未渲染')
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

  console.log(JSON.stringify({
    ok: true,
    practiceStem,
    pendingCount,
    bulk: {
      pendingCount,
      disabledBeforeSelect: bulkDisabledBefore,
      countAfterSelect,
      countAfterSelectAll,
      countAfterUnselect,
    },
    problems,
  }, null, 2))
  if (problems.length) process.exitCode = 1
} catch (error) {
  await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true })
  console.error('SMOKE FAILED:', error)
  console.error('problems:', problems)
  process.exitCode = 1
} finally {
  await browser.close()
}
