/**
 * 创造模式端到端：新建智能体 → 卡片出现 → 使用 → 对话页出现提示条 → 删除。
 * 用法：node e2e/audit-studio.mjs
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const OUT = 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  locale: 'zh-CN',
  reducedMotion: 'reduce',
})
const page = await context.newPage()
page.setDefaultTimeout(12000)
const errors = []
page.on('pageerror', (err) => errors.push(String(err).split('\n')[0].slice(0, 140)))

const results = []
const record = (label, ok, detail) => {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label} — ${detail}`)
}

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
await page.waitForSelector('.workspace-sider', { timeout: 20000 })
await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })

const navLabels = (await page.locator('.sidebar-nav-item .sidebar-nav-label').allInnerTexts()).map((t) => t.trim())
record('侧边栏不含「创造模式」', !navLabels.includes('创造模式'), navLabels.join(' / '))

// 创造模式的唯一入口在运行模式下拉的「创造」一项里（侧边栏没有它）。
// 先回对话页，再经模式下拉跳转。
const gotoStudioViaModeMenu = async () => {
  await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
  await page.waitForSelector('.chat-stage', { timeout: 20000 })
  await page.waitForTimeout(1600)
  await page.locator('.composer-actions-left .composer-chip').nth(0).click()
  await page.waitForSelector('.composer-mode-menu .ant-dropdown-menu-item', { timeout: 10000 })
  await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
  await page.waitForSelector('.studio-page', { timeout: 20000 })
}
await gotoStudioViaModeMenu()
await page.waitForTimeout(1800)
record('创造模式页面渲染', true, '经运行模式下拉进入 studio-page')

// 空态下先建一个
const name = `验收智能体${Date.now() % 100000}`
await page.locator('.studio-page button', { hasText: /新\s*建\s*智\s*能\s*体/ }).first().click()
await page.waitForSelector('.ant-modal-wrap:visible', { timeout: 10000 })
await page.waitForTimeout(500)
await page.locator('.ant-modal-wrap:visible input').nth(0).fill(name)
await page.locator('.ant-modal-wrap:visible input').nth(1).fill('核对接口实现与文档是否一致')
await page.locator('.ant-modal-wrap:visible textarea').first().fill('你是接口验收助手。逐条比对实现与文档，指出不一致处并给出最小复现。')
await page.screenshot({ path: `${OUT}/22-studio-form.png` })
await page.locator('.ant-modal-wrap:visible .ant-btn-primary').last().click()
await page.waitForTimeout(2000)
const cardTitles = (await page.locator('.studio-card-head .ant-typography').allInnerTexts()).map((t) => t.trim())
record('新建后卡片出现', cardTitles.includes(name), `${cardTitles.length} 张卡片：${cardTitles.slice(0, 4).join(' / ')}`)
await page.screenshot({ path: `${OUT}/23-studio-list.png` })

// 人设为空必须被拦住
await page.locator('.studio-page button', { hasText: /新\s*建\s*智\s*能\s*体/ }).first().click()
await page.waitForSelector('.ant-modal-wrap:visible', { timeout: 10000 })
await page.locator('.ant-modal-wrap:visible input').nth(0).fill('缺人设的智能体')
await page.locator('.ant-modal-wrap:visible .ant-btn-primary').last().click()
await page.waitForTimeout(900)
const stillOpen = await page.locator('.ant-modal-wrap:visible').count()
record('人设为空被拦下', stillOpen > 0, stillOpen ? '弹窗保持打开并给出提示' : '❌ 竟然提交了')
await page.locator('.ant-modal-wrap:visible button', { hasText: /取\s*消/ }).first().click()
await page.waitForTimeout(600)

// 使用：应切到对话页并显示提示条
const card = page.locator('.studio-card').filter({ hasText: name }).first()
await card.locator('button', { hasText: /^使\s*用$/ }).first().click()
await page.waitForTimeout(2500)
const stripText = await page.locator('.composer-agent-strip').innerText().catch(() => '')
record('使用后对话页显示当前智能体', stripText.includes(name), stripText.replace(/\n/g, ' | ').slice(0, 90))
await page.screenshot({ path: `${OUT}/24-studio-in-chat.png` })

// 退出该智能体
await page.locator('.composer-agent-clear').click()
await page.waitForTimeout(1200)
record('可退出该智能体', (await page.locator('.composer-agent-strip').count()) === 0, '提示条已消失')

// 删除
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 20000 })
await page.waitForTimeout(1500)
await page.locator('.composer-actions-left .composer-chip').nth(0).click()
await page.waitForTimeout(600)
await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
await page.waitForSelector('.studio-page', { timeout: 20000 })
await page.waitForTimeout(1500)
const target = page.locator('.studio-card').filter({ hasText: name }).first()
await target.locator('button', { hasText: /删\s*除/ }).first().click()
await page.waitForTimeout(700)
await page.locator('.ant-popover:visible button', { hasText: /删\s*除/ }).first().click()
await page.waitForTimeout(2000)
const after = (await page.locator('.studio-card-head .ant-typography').allInnerTexts()).map((t) => t.trim())
record('删除后卡片消失', !after.includes(name), `剩 ${after.length} 张`)

// 从运行模式下拉进入创造模式：这是用户要求的主入口
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 20000 })
await page.waitForTimeout(2000)
await page.locator('.composer-actions-left .composer-chip').nth(0).click()
await page.waitForTimeout(700)
const menuLabels = (await page.locator('.composer-mode-menu .ant-dropdown-menu-item').allInnerTexts()).map((t) => t.trim())
record('运行模式下拉含「创造」', menuLabels.some((t) => t.split('\n')[0].trim() === '创造'), menuLabels.map((t) => t.split('\n')[0]).join(' / '))
await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
await page.waitForSelector('.studio-page', { timeout: 20000 })
const stillChat = await page.locator('.chat-stage').count()
record('从模式下拉进入创造模式', stillChat === 0, '已切换到 studio-page')
await page.screenshot({ path: `${OUT}/25-studio-from-mode.png` })

record('无运行时错误', errors.length === 0, errors.slice(0, 2).join(' | ') || '0 条')

console.log(`\n创造模式体检：${results.filter((r) => r.ok).length}/${results.length} 通过`)
for (const item of results.filter((r) => !r.ok)) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
process.exit(results.every((r) => r.ok) ? 0 : 1)
