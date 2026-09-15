/** 临时：打开通知中心抽屉截图，用于视觉走查。 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const OUT = 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(20000)
page.on('pageerror', (err) => console.log('PAGEERROR:', String(err).slice(0, 160)))

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.evaluate(async () => {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
    body: JSON.stringify({ email: 'admin@futureagent.dev', password: 'ChangeMe123!' }),
  })
  const payload = await res.json()
  sessionStorage.setItem('futureagent.access_token', payload.access_token)
  sessionStorage.setItem('futureagent.workspace_id', payload.workspaces[0].id)
})
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForSelector('.workspace-sider', { timeout: 25000 })
await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 40000 })
await page.waitForTimeout(1500)

await page.locator('.ant-badge').first().click().catch(async () => {
  await page.locator('header button').last().click()
})
await page.waitForSelector('.notification-drawer', { timeout: 15000 })
await page.waitForTimeout(1200)
await page.screenshot({ path: `${OUT}/notify-01-list.png` })

// 只留未读再看一眼
const unreadTab = page.locator('.notification-filter .ant-segmented-item', { hasText: '未读' }).first()
if (await unreadTab.count()) {
  await unreadTab.click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/notify-02-unread.png` })
  await page.locator('.notification-filter .ant-segmented-item', { hasText: '全部' }).first().click()
  await page.waitForTimeout(500)
}

// hover 一行，看交互态
const row = page.locator('.notification-row').nth(1)
if (await row.count()) {
  await row.hover()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}/notify-03-hover.png` })
}

// 深色模式：走应用自己的开关，antd 主题与变量才会一起切
await page.keyboard.press('Escape')
await page.waitForTimeout(600)
await page.locator('.sidebar-account').click()
await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
// 当前是浅色就点「切换到深色」，已经是深色则什么都不用做
const toDark = page.locator('.ant-dropdown-menu-item', { hasText: '切换到深色' }).first()
if (await toDark.count()) await toDark.click()
else await page.keyboard.press('Escape')
await page.waitForTimeout(1200)
await page.locator('.ant-badge').first().click().catch(() => {})
await page.waitForSelector('.notification-drawer', { timeout: 10000 })
await page.waitForTimeout(1200)
await page.screenshot({ path: `${OUT}/notify-04-dark.png` })

// 切回浅色，避免影响后续手工查看
await page.keyboard.press('Escape')
await page.waitForTimeout(500)
await page.locator('.sidebar-account').click()
await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
const toLight = page.locator('.ant-dropdown-menu-item', { hasText: '切换到浅色' }).first()
if (await toLight.count()) await toLight.click()
else await page.keyboard.press('Escape')
await page.waitForTimeout(800)

console.log('截图已写入 e2e/screens/notify-*.png')
await browser.close()
