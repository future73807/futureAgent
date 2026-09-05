// E2E 冒烟测试：登录 → 看板任务抽屉改状态 → 工作模式批次历史钻取。
// 运行前提：API(8000) 与前端 preview(8899) 已启动。
// 用法：node e2e/smoke.mjs
// 浏览器：优先本机 Edge/Chrome（无需下载浏览器二进制）。
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:8899'
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`)
}

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (err) => errors.push(String(err)))

  // ---- 1. 登录态注入并进入工作台 ----
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.evaluate(async () => {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email: 'admin@futureagent.dev', password: 'ChangeMe123!' }),
    })
    const payload = await res.json()
    sessionStorage.setItem('futureagent.access_token', payload.access_token)
    sessionStorage.setItem('futureagent.workspace_id', payload.workspaces[0].id)
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.workspace-sider', { timeout: 15000 })
  check('登录后工作台渲染', true)

  // ---- 2. 项目看板：打开任务抽屉并切换状态 ----
  await page.getByText('项目看板', { exact: true }).first().click()
  await page.waitForSelector('.task-card', { timeout: 15000 })
  const beforeTitle = await page.locator('.task-card').first().locator('strong').textContent()
  await page.locator('.task-card').first().click()
  await page.waitForSelector('.ant-drawer-open', { timeout: 10000 })
  check('任务抽屉打开', true, beforeTitle || '')

  // 抽屉内第一个下拉是状态：切到"已完成"
  await page.locator('.ant-drawer-open .ant-select').first().click()
  await page.waitForSelector('.ant-select-item-option', { timeout: 5000 })
  await page.locator('.ant-select-item-option', { hasText: '已完成' }).first().click()
  await page.waitForTimeout(1500)
  const drawerText = await page.locator('.ant-drawer-open').textContent()
  check('任务状态切换为已完成', drawerText.includes('已完成'))

  // 关闭抽屉再进行后续页面操作（遮罩会拦截点击）
  await page.locator('.ant-drawer-open .ant-drawer-close').click()
  await page.waitForTimeout(800)

  // ---- 3. 工作模式：批次历史钻取 ----
  await page.getByText('工作模式', { exact: true }).first().click()
  await page.waitForSelector('.project-selector', { timeout: 15000 })
  // 选中带批次数据的任务
  await page.locator('.project-selector .ant-select-selector').click()
  await page.waitForSelector('.ant-select-item-option', { timeout: 5000 })
  await page.locator('.ant-select-item-option', { hasText: '排序任务 1' }).first().click()
  await page.waitForTimeout(3000)
  await page.waitForTimeout(500)
  await page.locator('.batch-history .ant-collapse-item').first().locator('.ant-collapse-header').click()
  await page.waitForTimeout(600)
  await page.locator('.batch-history button', { hasText: '加载本批执行明细' }).first().click()
  await page.waitForSelector('.batch-run-row', { timeout: 10000 })
  const runRows = await page.locator('.batch-run-row').count()
  check('批次详情钻取渲染 run 行', runRows >= 2, `rows=${runRows}`)
  const hasStatusBadge = await page.locator('.batch-run-row .ant-tag').first().textContent()
  check('批次 run 终态徽标显示', Boolean(hasStatusBadge), hasStatusBadge || '')

  // ---- 4. 语言切换 ----
  await page.locator('button[aria-label="切换语言 / Switch language"]').click()
  await page.waitForTimeout(600)
  const navEn = await page.evaluate(() => document.querySelector('.workspace-sider')?.textContent.includes('AI Chat'))
  check('语言切换至英文', Boolean(navEn))
  await page.locator('button[aria-label="切换语言 / Switch language"]').click()
  await page.waitForTimeout(400)

  // ---- 5. 无运行时错误 ----
  const runtimeErrors = await page.evaluate(() => window.__runtimeErrors || [])
  check('无运行时错误', runtimeErrors.length === 0, runtimeErrors.join('; '))

  const failed = results.filter((r) => !r.ok)
  console.log(`\n== E2E 冒烟：${results.length - failed.length}/${results.length} 通过 ==`)
  process.exitCode = failed.length ? 1 : 0
} finally {
  await browser.close()
}
