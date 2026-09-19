/**
 * 视觉回归截图：选中态、提示条、导航、品牌标记。
 * 用法：node e2e/screens-style.mjs
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const OUT = process.env.SCREEN_DIR || 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(12000)

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.evaluate(async () => {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email: 'admin@futureagent.dev', password: 'ChangeMe123!' }),
  })
  const payload = await res.json()
  sessionStorage.setItem('futureaccess_tok', '')
  sessionStorage.setItem('futureagent.access_token', payload.access_token)
  sessionStorage.setItem('futureagent.workspace_id', payload.workspaces[0].id)
})
await page.reload({ waitUntil: 'domcontentloaded' })
await page.waitForSelector('.workspace-sider', { timeout: 20000 })
await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })

// 导航：工作模式应当已不在列表里
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 20000 })
await page.waitForTimeout(2200)
const navLabels = (await page.locator('.sidebar-nav-item .sidebar-nav-label').allInnerTexts()).map((t) => t.trim())
console.log('侧边栏导航：', navLabels.join(' / '))
console.log(['工作模式', '创造模式'].some((k) => navLabels.includes(k)) ? '❌ 工作模式/创造模式仍在导航里' : '✅ 二者均不在导航（创造入口在运行模式下拉）')

// 运行模式下拉的选中态
await page.locator('.composer-actions-left .composer-chip').nth(0).click()
await page.waitForTimeout(700)
const selectedStyle = await page.evaluate(() => {
  const item = document.querySelector('.ant-dropdown-menu-item-selected')
  if (!item) return null
  const style = getComputedStyle(item)
  const probe = document.createElement('span')
  probe.style.color = style.color
  document.body.appendChild(probe)
  const textColor = getComputedStyle(probe).color
  probe.remove()
  return { background: style.backgroundColor, color: style.color, text: (item.innerText || '').split('\n')[0] }
})
console.log('选中项样式：', JSON.stringify(selectedStyle))
await page.screenshot({ path: `${OUT}/20-dropdown-selected.png` })
await page.keyboard.press('Escape')
await page.waitForTimeout(400)

// 知识库页：文档卡片与提示文案
await page.locator('.sidebar-nav-item', { hasText: '知识库' }).first().click()
await page.waitForSelector('.kb-page', { timeout: 20000 }).catch(() => {})
await page.waitForTimeout(2000)
await page.screenshot({ path: `${OUT}/21-knowledge.png` })

console.log('screens written to', OUT)
await browser.close()
