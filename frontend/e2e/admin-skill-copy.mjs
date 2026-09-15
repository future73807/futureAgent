/**
 * 管理端技能「复制」的回归验收（对应修复：POST /v1/skills/{name}/copy 曾返回 500）。
 * 用法：cd frontend && node e2e/admin-skill-copy.mjs
 */
import { chromium } from 'playwright-core'

const ADMIN = process.env.E2E_ADMIN_URL || 'http://localhost:5174'
const results = []
const record = (label, ok, detail) => {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label} — ${detail}`)
}

const browser = await chromium.launch({ channel: 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
page.setDefaultTimeout(20000)
const failures = []
page.on('response', (res) => {
  if (res.url().includes('/api/v1/skills/') && res.status() >= 400) failures.push(`${res.request().method()} ${res.url()} → ${res.status()}`)
})

await page.goto(ADMIN, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2500)
const email = page.locator('input[placeholder="name@company.com"]')
if (await email.count()) {
  await email.fill('admin@futureagent.dev')
  await page.locator('input[placeholder="请输入登录密码"]').fill('ChangeMe123!')
  await page.getByRole('button', { name: /进入管理后台/ }).first().click()
}
await page.waitForSelector('.ant-layout-sider', { timeout: 25000 })
await page.locator('.ant-menu-item', { hasText: '技能管理' }).first().click()
await page.waitForTimeout(1500)

const row = page.locator('.ant-table-row', { hasText: 'python_demo_guardian' }).first()
record('技能列表可见验收技能', (await row.count()) > 0, 'python_demo_guardian_*')

await row.getByRole('button', { name: /复\s*制/ }).click()
await page.waitForTimeout(2500)
const copied = await page.locator('.ant-table-row', { hasText: 'python_demo_guardian_82637-copy' }).count()
record('复制技能返回成功并出现在列表', copied > 0, copied ? 'python_demo_guardian_82637-copy' : '未出现副本')
await page.screenshot({ path: 'e2e/screens/admin-skill-copy.png' }).catch(() => {})

if (copied) {
  const copyRow = page.locator('.ant-table-row', { hasText: '-copy' }).first()
  await copyRow.getByRole('button', { name: /删\s*除/ }).click()
  await page.waitForTimeout(600)
  await page.locator('.ant-popconfirm button.ant-btn-primary, .ant-popover button.ant-btn-primary').first().click()
  await page.waitForTimeout(2000)
  const left = await page.locator('.ant-table-row', { hasText: '-copy' }).count()
  record('删除副本清理干净', left === 0, left ? `仍剩 ${left} 行` : '已删除')
}

record('复制链路无 4xx/5xx', failures.length === 0, failures.join(' | ') || '无')
const passed = results.filter((r) => r.ok).length
console.log(`\n== 技能复制回归：${passed}/${results.length} 通过 ==`)
await browser.close()
