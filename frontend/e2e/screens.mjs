/**
 * 视觉走查截图：按顺序把用户端的每个页面截一张图，放进 e2e/screens/。
 * 改样式后跑一遍，比逐个页面点开看快得多。
 *
 * 用法：node e2e/screens.mjs
 *   E2E_BASE_URL  默认 http://localhost:5173
 *   SCREEN_DIR    默认 e2e/screens
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const OUT = process.env.SCREEN_DIR || 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()

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
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/01-code-home.png` })

// 空态首屏：新建一个任务，截 Code 工作台的主视觉
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage.is-empty', { timeout: 15000 })
await page.waitForTimeout(900)
await page.screenshot({ path: `${OUT}/02-code-empty.png` })

const routes = [
  ['项目看板', '03-board'],
  ['插件市场', '04-market'],
  ['汇报智能体', '06-report'],
  ['经营助手', '07-business'],
  ['团队成员', '08-team'],
]
for (const [label, file] of routes) {
  await page.keyboard.press('Escape')
  await page.locator('.sidebar-nav-item', { hasText: label }).first().click()
  await page.waitForTimeout(1800)
  await page.screenshot({ path: `${OUT}/${file}.png` })
  if (label === '插件市场') {
    // 技能页签：精选卡片、分类与卡片网格（必须在市场页还开着的时候截）
    await page.locator('.market-toolbar .ant-segmented-item', { hasText: '技能' }).click()
    await page.waitForSelector('.market-card', { timeout: 15000 })
    await page.waitForTimeout(900)
    await page.screenshot({ path: `${OUT}/09-market-skills.png` })
  }
}

// 设置面板：账号 / 权限审批 / 规则与记忆 / 浏览器 / 模型
const openSettings = async () => {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.locator('.sidebar-account').click()
    try {
      await page.waitForFunction(
        () => [...document.querySelectorAll('.ant-dropdown-menu-item')]
          .some((el) => el.offsetParent !== null && (el.innerText || '').trim() === '设置'),
        null,
        { timeout: 4000 },
      )
      return
    } catch { await page.waitForTimeout(400) }
  }
  throw new Error('账号菜单未展开')
}
await openSettings()
await page.locator('.ant-dropdown-menu-item:visible', { hasText: /^设置$/ }).first().click()
await page.waitForSelector('.settings-modal', { timeout: 15000 })
await page.waitForTimeout(900)
await page.screenshot({ path: `${OUT}/10-settings-account.png` })

const sections = [
  ['权限审批', '11-settings-permission'],
  ['模型', '12-settings-models'],
  ['规则与记忆', '13-settings-rules'],
  ['浏览器', '14-settings-browser'],
  ['用量管理', '15-settings-usage'],
]
for (const [label, file] of sections) {
  await page.locator('.settings-nav-item', { hasText: label }).first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}/${file}.png` })
}
await page.locator('.settings-close').click()
await page.waitForTimeout(500)

// 工作区设置页仍可从账号菜单进入（通知出口、所有权转移等）
await page.locator('.sidebar-account').click()
await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
await page.locator('.ant-dropdown-menu-item:visible', { hasText: '工作区设置' }).first().click()
await page.waitForSelector('.settings-page', { timeout: 15000 })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/16-workspace-settings.png` })

// 通知中心：分组、来源图标、语义色与相对时间都是新设计，单独留档
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 15000 })
await page.waitForTimeout(800)
await page.locator('.ant-badge').first().click()
await page.waitForSelector('.notification-drawer', { timeout: 15000 })
await page.waitForTimeout(1000)
await page.screenshot({ path: `${OUT}/18-notifications.png` })
const unreadTab = page.locator('.notification-filter .ant-segmented-item', { hasText: '未读' }).first()
if (await unreadTab.count()) {
  await unreadTab.click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}/19-notifications-unread.png` })
}
await page.keyboard.press('Escape')
await page.waitForTimeout(500)

// 深色主题：确认中性色在暗色下也成立
await page.locator('button[aria-label="切换深浅色主题"]').click()
await page.waitForTimeout(900)
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 15000 })
await page.waitForTimeout(1200)
await page.screenshot({ path: `${OUT}/17-dark.png` })

// 看板在深色下的工具栏与按钮（夜间对比度回归点）
await page.locator('.sidebar-nav-item', { hasText: '项目看板' }).click()
await page.waitForSelector('.board-filters', { timeout: 20000 })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${OUT}/20-dark-board.png` })

await browser.close()
console.log('screens written to', OUT)
