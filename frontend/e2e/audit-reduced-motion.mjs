/**
 * "减少动态效果"环境下的浮层体检。
 *
 * 系统打开 Windows 辅助功能里的"减少动态效果"（prefers-reduced-motion: reduce）时，
 * 曾经所有下拉都打不开：浮层停在测量用的视口外坐标（left: -12800px），同时把一个
 * 绝对定位元素撑出 13061px 的文档宽度，闪出一条横向滚动条——用户看到的就是
 * "点了没反应 + 页面闪一下"。根因是 CSS 里用 `*` 覆盖了 transition/animation 时长。
 *
 * 这类环境级差异不会出现在默认 CI 里（headless 默认 no-preference），必须显式模拟。
 */
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  // 与 Windows 真实浏览器一致：滚动条占位 9px，不做隐藏。
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  locale: 'zh-CN',
  reducedMotion: 'reduce',
})
const page = await context.newPage()
page.setDefaultTimeout(9000)

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

const reduced = await page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
record('环境已模拟 reduced motion', reduced, `prefers-reduced-motion: reduce = ${reduced}`)

await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage', { timeout: 20000 })
await page.waitForTimeout(2200)

/** 点开一个控件，要求：浮层在视口内可见、文档不被撑宽撑高。 */
const checkPopup = async (label, open, popupSelector) => {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(250)
  await page.locator('.workspace-header').click({ position: { x: 3, y: 3 }, timeout: 3000 }).catch(() => {})
  await page.waitForTimeout(250)

  // 逐帧记录文档尺寸，捕捉"滚动条闪一下"
  await page.evaluate(() => {
    window.__trace = []
    window.__traceTimer = setInterval(() => {
      window.__trace.push([document.documentElement.scrollWidth, document.documentElement.scrollHeight])
    }, 16)
  })
  try {
    await open()
  } catch (error) {
    await page.evaluate(() => clearInterval(window.__traceTimer))
    record(label, false, `点击失败：${String(error.message).split('\n')[0].slice(0, 100)}`)
    return
  }
  await page.waitForTimeout(900)
  const state = await page.evaluate((sel) => {
    clearInterval(window.__traceTimer)
    const nodes = [...document.querySelectorAll(sel)].filter((el) => {
      const rect = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
    })
    const rect = nodes[0]?.getBoundingClientRect()
    const trace = window.__trace || []
    return {
      visible: nodes.length,
      box: rect ? `${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}x${Math.round(rect.height)}` : null,
      insideViewport: rect
        ? rect.left >= -1 && rect.top >= -1 && rect.right <= window.innerWidth + 1 && rect.bottom <= window.innerHeight + 1
        : false,
      maxScrollW: Math.max(...trace.map((t) => t[0]), 0),
      clientW: document.documentElement.clientWidth,
      viewportW: window.innerWidth,
    }
  }, popupSelector)

  const ok = state.visible > 0 && state.insideViewport && state.maxScrollW <= state.clientW + 1
  record(
    label,
    ok,
    state.visible === 0
      ? '❌ 浮层没出现'
      : `${state.box} 视口内=${state.insideViewport}｜过程中文档最大宽 ${state.maxScrollW}（可用 ${state.clientW}）${state.maxScrollW > state.clientW + 1 ? ' ❌ 闪出横向滚动条' : ''}`,
  )
}

await checkPopup('账号菜单', () => page.locator('.sidebar-account').click(), '.ant-dropdown')
await checkPopup('工作区选择器', () => page.locator('.sidebar-workspace-select').click(), '.ant-select-dropdown')
await checkPopup('顶栏·深浅色主题', () => page.locator('button[aria-label="切换深浅色主题"]').click(), '.ant-dropdown, .ant-tooltip')
await checkPopup('输入卡 chip[0] 运行模式', () => page.locator('.composer-actions-left .composer-chip').nth(0).click(), '.ant-dropdown')
await checkPopup('输入卡 chip[1] 模型', () => page.locator('.composer-actions-left .composer-chip').nth(1).click(), '.ant-dropdown')
await checkPopup('输入卡 chip[2] 技能', () => page.locator('.composer-actions-left .composer-chip').nth(2).click(), '.ant-dropdown')
await checkPopup('输入卡 chip[3] 工具', () => page.locator('.composer-actions-left .composer-chip').nth(3).click(), '.ant-dropdown')
await checkPopup('输入卡 chip[4] 授权档位', () => page.locator('.composer-actions-left .composer-chip').nth(4).click(), '.ant-dropdown')
await checkPopup('任务列表更多菜单', () => page.locator('.ant-conversations-menu-icon').first().click(), '.ant-dropdown')

// 侧边栏导航在 reduced motion 下也必须能切页
for (const [label, sel] of [['项目看板', '.page-shell'], ['插件市场', '.market-page'], ['团队成员', '.page-heading']]) {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(250)
  try {
    await page.locator('.sidebar-nav-item', { hasText: label }).first().click()
    await page.waitForSelector(sel, { timeout: 15000 })
    record(`导航可切换：${label}`, true, '页面已渲染')
  } catch (error) {
    record(`导航可切换：${label}`, false, `失败：${String(error.message).split('\n')[0].slice(0, 100)}`)
  }
}

console.log(`\n减少动效体检：${results.filter((r) => r.ok).length}/${results.length} 通过`)
for (const item of results.filter((r) => !r.ok)) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
