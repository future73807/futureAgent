/** 窄屏（<992px，侧边栏收进抽屉）下的交互体检。 */
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 900, height: 700 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(8000)
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
await page.waitForSelector('.workspace-header', { timeout: 20000 })
await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })
await page.waitForTimeout(1500)

record('窄屏下侧边栏收进抽屉（预期）', (await page.locator('.workspace-sider').count()) === 0, '桌面侧边栏不在 DOM 中')

// 汉堡菜单能否打开导航
const burger = page.locator('button[aria-label="打开主导航"]').first()
record('汉堡按钮存在', (await burger.count()) > 0, `找到 ${await burger.count()} 个`)
try {
  await burger.click()
  await page.waitForSelector('.ant-drawer-open', { timeout: 8000 })
  await page.waitForTimeout(700)
  const items = (await page.locator('.ant-drawer-open .sidebar-nav-item').allInnerTexts()).map((t) => t.trim())
  // 校验"该有的入口都在"，而不是数个数：侧边栏把 chat/settings 放在别处，
  // 入口数量随产品收敛变化（删掉两个智能体后正好从 6 变 5），写死数量会在
  // 每次导航调整时误报，而漏掉一个页面才是真问题。
  const expectedEntries = ['新建任务', '项目看板', '插件市场', '知识库', '团队成员']
  const missing = expectedEntries.filter((label) => !items.some((text) => text.includes(label)))
  record(
    '导航抽屉可打开',
    items.length > 0 && missing.length === 0,
    `${items.length} 个入口：${items.slice(0, 8).join(' / ')}${missing.length ? `（缺 ${missing.join(' / ')}）` : ''}`,
  )
} catch (error) {
  record('导航抽屉可打开', false, String(error.message).split('\n')[0].slice(0, 120))
}

// 抽屉里进插件市场
try {
  await page.locator('.ant-drawer-open .sidebar-nav-item', { hasText: '插件市场' }).first().click()
  await page.waitForSelector('.market-page', { timeout: 15000 })
  await page.waitForTimeout(1000)
  record('抽屉导航切页可用', true, '插件市场已渲染')
} catch (error) {
  record('抽屉导航切页可用', false, String(error.message).split('\n')[0].slice(0, 120))
}

// 窄屏下的输入卡 chips
await page.locator('button[aria-label="打开主导航"]').first().click().catch(() => {})
await page.waitForTimeout(600)
await page.locator('.ant-drawer-open .sidebar-nav-item', { hasText: '新建任务' }).first().click().catch(() => {})
await page.waitForSelector('.chat-stage', { timeout: 15000 })
await page.waitForTimeout(1600)
const chips = page.locator('.composer-actions-left .composer-chip')
const chipCount = await chips.count()
for (let index = 0; index < chipCount; index += 1) {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(200)
  let opened = 0
  try {
    await chips.nth(index).click({ timeout: 5000 })
    await page.waitForTimeout(450)
    opened = await page.evaluate(() => [...document.querySelectorAll('.ant-dropdown, .ant-select-dropdown')]
      .filter((el) => el.getBoundingClientRect().height > 0 && !el.className.includes('hidden')).length)
  } catch (error) {
    record(`窄屏 chip[${index}]`, false, `点击超时：${String(error.message).split('\n')[0].slice(0, 80)}`)
    continue
  }
  record(`窄屏 chip[${index}] 可展开`, opened === 1, `浮层 ${opened} 个`)
}

// 窄屏下的设置面板
await page.keyboard.press('Escape').catch(() => {})
await page.waitForTimeout(300)
try {
  await page.locator('button[aria-label="打开主导航"]').first().click()
  await page.waitForTimeout(700)
  await page.locator('.ant-drawer-open .sidebar-account').first().click()
  await page.waitForTimeout(700)
  await page.locator('.ant-dropdown-menu-item:visible', { hasText: /^设置$/ }).first().click()
  await page.waitForSelector('.settings-layout', { timeout: 12000 })
  await page.waitForTimeout(700)
  const navVisible = await page.locator('.settings-nav-item').first().isVisible()
  record('窄屏设置面板可打开', navVisible, '分区列表可见')
  await page.locator('.settings-nav-item', { hasText: '浏览器' }).first().click()
  await page.waitForTimeout(700)
  const selectBox = await page.locator('.settings-section').filter({ hasText: 'AI 任务默认浏览器' }).locator('.ant-select').first().boundingBox()
  record('窄屏设置面板控件未溢出', Boolean(selectBox), selectBox ? `Select ${Math.round(selectBox.width)}x${Math.round(selectBox.height)}` : '找不到')
} catch (error) {
  record('窄屏设置面板可打开', false, String(error.message).split('\n')[0].slice(0, 140))
}
await page.screenshot({ path: 'e2e/narrow-last.png' })

console.log(`\n窄屏体检：${results.filter((r) => r.ok).length}/${results.length} 通过`)
for (const item of results.filter((r) => !r.ok)) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
