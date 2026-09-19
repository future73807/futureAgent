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

/** 删掉列表里所有 -copy 行（含上一次崩溃留下的），返回剩余行数。 */
const purgeCopies = async () => {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const copyRows = page.locator('.ant-table-row', { hasText: '-copy' })
    if (!(await copyRows.count())) break
    await copyRows.first().getByRole('button', { name: /删\s*除/ }).click()
    await page.waitForTimeout(600)
    await page.locator('.ant-popconfirm button.ant-btn-primary, .ant-popover button.ant-btn-primary').first().click()
    await page.waitForTimeout(1500)
  }
  return page.locator('.ant-table-row', { hasText: '-copy' }).count()
}

// 先清残留：上一次运行若在断言处失败，-copy 行会留到下一次，导致"第一行"变成副本。
await purgeCopies()

// 源行排除 -copy：副本名 = 源技能名 + "-copy"，不能拿副本再复制一层。
const row = page.locator('.ant-table-row', { hasText: 'python_demo_guardian' }).filter({ hasNotText: '-copy' }).first()
record('技能列表可见验收技能', (await row.count()) > 0, 'python_demo_guardian*')

// 副本名由服务端按「源技能名 + -copy」生成：写死某个具体名字（曾经是
// python_demo_guardian_82637-copy）下一轮必然失效，这里从当前源行推出。
const sourceName = (await row.locator('td').first().innerText()).trim().split('\n')[0]
const expectedCopy = `${sourceName}-copy`
await row.getByRole('button', { name: /复\s*制/ }).click()
await page.waitForTimeout(2500)
const copied = await page.locator('.ant-table-row', { hasText: expectedCopy }).count()
record('复制技能返回成功并出现在列表', copied > 0, copied ? expectedCopy : `未出现副本 ${expectedCopy}`)
await page.screenshot({ path: 'e2e/screens/admin-skill-copy.png' }).catch(() => {})

if (copied) {
  const left = await purgeCopies()
  record('删除副本清理干净', left === 0, left ? `仍剩 ${left} 行` : '已删除')
}

record('复制链路无 4xx/5xx', failures.length === 0, failures.join(' | ') || '无')
const passed = results.filter((r) => r.ok).length
console.log(`\n== 技能复制回归：${passed}/${results.length} 通过 ==`)
await browser.close()
