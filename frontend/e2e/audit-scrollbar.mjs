/**
 * 滚动条 / 布局位移体检。
 *
 * 用户报的现象是"点下拉框什么选项也没有，还会出现滚动条造成布局闪烁"。
 * 这里把它拆成三条可断言的事实：
 *   1. 应用外壳自身不产生页面级滚动条（滚动只发生在内容区内部）；
 *   2. 即使页面被迫出现滚动条，内容列也不能横移（scrollbar-gutter 已预留）；
 *   3. 贴在窗口下沿的下拉框必须整体落在视口内，不能翻到屏幕外面去。
 */
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
// 用户截图折算下来是一个偏矮的窗口，短窗口正是这类问题的高发区。
const SIZES = [
  [1280, 624],
  [1440, 900],
  [1366, 580],
  [1024, 560],
]

// 关键：Playwright 的 headless 默认带 --hide-scrollbars，滚动条宽度为 0，
// 于是"滚动条一出现内容就横移"在体检里完全看不见（Windows 真实浏览器是 15px）。
// 这里关掉该默认参数，让体检环境与用户环境一致。
const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const results = []
const record = (label, ok, detail) => {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label} — ${detail}`)
}

const columnEdges = () => page.evaluate(() => {
  const content = document.querySelector('.workspace-content')?.getBoundingClientRect()
  const sider = document.querySelector('.workspace-sider')?.getBoundingClientRect()
  return {
    clientW: document.documentElement.clientWidth,
    siderLeft: sider ? Math.round(sider.left) : null,
    contentLeft: content ? Math.round(content.left) : null,
    contentRight: content ? Math.round(content.right) : null,
  }
})

let page
for (const [width, height] of SIZES) {
  const context = await browser.newContext({ viewport: { width, height }, locale: 'zh-CN' })
  page = await context.newPage()
  page.setDefaultTimeout(8000)
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
  await page.waitForTimeout(1400)

  const tag = `${width}x${height}`

  // 1. 外壳自身不滚动
  const shell = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    scrollH: document.documentElement.scrollHeight,
    clientH: document.documentElement.clientHeight,
    gutter: getComputedStyle(document.documentElement).scrollbarGutter,
    layoutOverflow: getComputedStyle(document.querySelector('.workspace-layout')).overflow,
  }))
  record(
    `${tag} 应用外壳不产生页面滚动`,
    shell.scrollH <= shell.clientH + 1,
    `scrollH=${shell.scrollH} clientH=${shell.clientH}，overflow=${shell.layoutOverflow}，gutter=${shell.gutter}`,
  )

  // 2. 跨页面宽度稳定：这是用户报的"布局抖动"的直接回归断言。
  //    内容区若没预留滚动条槽位，某个页面内容一变高就会冒出 9px 滚动条，
  //    整个内容区（含输入卡）横移 9px。
  const widths = []
  const measure = async (label) => {
    const m = await page.evaluate(() => {
      const content = document.querySelector('.workspace-content')
      const composer = document.querySelector('.composer-card')
      const sider = document.querySelector('.workspace-sider')
      return {
        contentClientW: content?.clientWidth ?? null,
        contentGutter: content ? content.offsetWidth - content.clientWidth : null,
        composerLeft: composer ? Math.round(composer.getBoundingClientRect().left) : null,
        contentLeft: content ? Math.round(content.getBoundingClientRect().left) : null,
        siderRight: sider ? Math.round(sider.getBoundingClientRect().right) : null,
        docScrollW: document.documentElement.scrollWidth,
        docClientW: document.documentElement.clientWidth,
      }
    })
    widths.push({ label, ...m })
    return m
  }
  await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
  await page.waitForSelector('.chat-stage', { timeout: 20000 })
  await page.waitForTimeout(1400)
  await measure('对话页')
  for (const [label, sel] of [['项目看板', '.page-shell'], ['插件市场', '.market-page'],  ['团队成员', '.page-shell'], ['知识库', '.kb-page']]) {
    await page.keyboard.press('Escape').catch(() => {})
    await page.locator('.sidebar-nav-item', { hasText: label }).first().click()
    await page.waitForSelector(sel, { timeout: 20000 }).catch(() => {})
    await page.waitForTimeout(1100)
    await measure(label)
  }
  await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
  await page.waitForSelector('.chat-stage', { timeout: 20000 }).catch(() => {})
  await page.waitForTimeout(1200)
  await measure('回到对话页')

  const uniqueContent = [...new Set(widths.map((w) => w.contentClientW))]
  const uniqueSider = [...new Set(widths.map((w) => w.siderRight))]
  const uniqueDoc = [...new Set(widths.map((w) => w.docClientW))]
  record(
    `${tag} 切遍全部页面内容区宽度恒定`,
    uniqueContent.length === 1 && uniqueSider.length === 1,
    uniqueContent.length === 1
      ? `内容区恒为 ${uniqueContent[0]}px（侧栏右沿恒为 ${uniqueSider[0]}px，页面无滚动条）`
      : `❌ 出现 ${uniqueContent.length} 种宽度：${widths.map((w) => `${w.label}=${w.contentClientW}`).join(' / ')}`,
  )
  record(
    `${tag} 全程不出现页面级滚动条`,
    uniqueDoc.length === 1 && widths.every((w) => w.docScrollW <= w.docClientW + 1),
    `页面可用宽恒为 ${uniqueDoc.join('/')}px，各页 scrollWidth 均未超出`,
  )

  // 3. 各类浮层：必须整体在视口内，并且不能撑高文档（撑高就会冒出滚动条）
  const popupTargets = [
    ['账号菜单', '.ant-dropdown:not(.ant-dropdown-hidden)', async () => page.locator('.sidebar-account').click()],
    ['工作区选择器', '.ant-select-dropdown:not(.ant-select-dropdown-hidden)', async () => page.locator('.sidebar-workspace-select').click()],
    ['任务列表更多菜单', '.ant-dropdown:not(.ant-dropdown-hidden)', async () => page.locator('.ant-conversations-menu-icon').first().click()],
  ]
  // 输入卡 chips 在主区中部，同样要确认不会把文档撑高
  await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
  await page.waitForSelector('.chat-stage.is-empty', { timeout: 20000 })
  await page.waitForTimeout(1200)
  const chipCount = await page.locator('.composer-actions-left .composer-chip').count()
  for (let index = 0; index < chipCount; index += 1) {
    popupTargets.push([
      `输入卡 chip[${index}]`,
      '.ant-dropdown:not(.ant-dropdown-hidden)',
      async () => page.locator('.composer-actions-left .composer-chip').nth(index).click(),
    ])
  }

  for (const [label, selector, open] of popupTargets) {
    const docBefore = await page.evaluate(() => document.documentElement.scrollHeight)
    try {
      await open()
    } catch (error) {
      record(`${tag} ${label}`, false, `点击失败：${String(error.message).split('\n')[0].slice(0, 90)}`)
      continue
    }
    await page.waitForTimeout(800)
    const state = await page.evaluate((sel) => {
      const panel = [...document.querySelectorAll(sel)].find((el) => el.getBoundingClientRect().height > 0)
      if (!panel) return { open: false }
      const rect = panel.getBoundingClientRect()
      const items = [...panel.querySelectorAll('.ant-dropdown-menu-item, .ant-select-item, .composer-picker-item, .composer-tools-row')]
        .filter((el) => el.offsetParent !== null)
      return {
        open: true,
        box: `${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}x${Math.round(rect.height)}`,
        insideViewport: rect.top >= -1 && rect.bottom <= window.innerHeight + 1 && rect.left >= -1 && rect.right <= window.innerWidth + 1,
        itemCount: items.length,
        emptyItems: items.filter((el) => !(el.innerText || '').trim()).length,
        scrollH: document.documentElement.scrollHeight,
        clientH: document.documentElement.clientHeight,
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      }
    }, selector)
    record(
      `${tag} ${label} 展开后可见且有内容`,
      state.open && state.insideViewport && state.itemCount > 0 && state.emptyItems === 0,
      state.open
        ? `${state.itemCount} 项（空白 ${state.emptyItems}），${state.box}，视口内=${state.insideViewport}`
        : '❌ 没有展开',
    )
    record(
      `${tag} ${label} 不撑高文档、不产生滚动条`,
      state.scrollH <= state.clientH + 1 && state.scrollW <= state.clientW + 1,
      `文档 ${docBefore} → ${state.scrollH} 高 / ${state.scrollW} 宽（视口 ${state.clientH} / ${state.clientW}）`,
    )
    await page.keyboard.press('Escape')
    await page.waitForTimeout(350)
    await page.locator('.workspace-header').click({ position: { x: 3, y: 3 }, timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(250)
  }

  await page.screenshot({ path: `e2e/short-${width}x${height}.png` })
  await context.close()
}

console.log(`\n滚动条体检：${results.filter((r) => r.ok).length}/${results.length} 通过`)
for (const item of results.filter((r) => !r.ok)) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
