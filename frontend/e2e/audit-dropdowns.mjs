/**
 * 全站下拉控件体检。
 *
 * 计数只数"浮层根节点"：.composer-picker-panel / .composer-tools-panel 本身就
 * 渲染在 .ant-dropdown 里面，把两者都算上会把"一个下拉"误报成"两个"。
 * 用法：node e2e/audit-dropdowns.mjs
 */
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(6000)

const openPopups = () => page.evaluate(() => {
  const hidden = ['ant-dropdown-hidden', 'ant-select-dropdown-hidden', 'ant-popover-hidden']
  const roots = [...document.querySelectorAll('.ant-dropdown, .ant-select-dropdown, .ant-popover')]
    .filter((el) => !hidden.some((cls) => el.classList.contains(cls)))
    .filter((el) => {
      const rect = el.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden'
    })
  return roots.map((el) => {
    const rect = el.getBoundingClientRect()
    const hit = document.elementFromPoint(Math.round(rect.left + rect.width / 2), Math.round(rect.top + rect.height / 2))
    return {
      cls: String(el.className).split(' ')[0],
      size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
      hitInside: Boolean(hit && el.contains(hit)),
    }
  })
})

const results = []
const dismiss = async () => {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(220)
  // 收浮层要点在"确定没有交互元素"的地方：右下角是输入卡浮动工具条，
  // 点在那里会真的触发「打开项目看板」之类的动作，把后续诊断带偏。
  await page.locator('.workspace-header').click({ position: { x: 3, y: 3 }, timeout: 3000 }).catch(() => {})
  await page.waitForTimeout(260)
}

/** 点开一个控件，断言"只弹出一个可用浮层"。 */
let dumped = false
const dumpOnce = async (reason) => {
  if (dumped) return
  dumped = true
  const info = await page.evaluate(() => ({
    url: location.href,
    hasChatStage: Boolean(document.querySelector('.chat-stage')),
    chatStageClass: document.querySelector('.chat-stage')?.className || '',
    hasComposer: Boolean(document.querySelector('.composer-card')),
    hasActionsLeft: Boolean(document.querySelector('.composer-actions-left')),
    actionsLeftText: document.querySelector('.composer-actions-left')?.innerText?.replace(/\n/g, '|').slice(0, 160) || '',
    hasAuthCard: Boolean(document.querySelector('.auth-card')),
    bodyStart: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200),
  }))
  console.log(`\n[dump:${reason}]`, JSON.stringify(info, null, 2))
  await page.screenshot({ path: 'e2e/audit-dump.png' })
}

const check = async (label, locator, { keepOverlay = false, softDismiss = false } = {}) => {
  try {
    // keepOverlay：控件在弹窗/抽屉里，而 dismiss() 会按 Escape 把宿主一起收掉，
    // 于是每次都变成"控件不存在"。这类控件由调用方保证宿主已经打开。
    // softDismiss：只收起上一个下拉，不动宿主。抽屉/弹窗里的控件必须这样——按 Escape
    // 会把宿主一起关掉，下一个控件就"不存在"了；改成点标题栏的空白处。
    if (softDismiss) {
      const hostHeader = page.locator('.ant-drawer-open .ant-drawer-header, .ant-modal-wrap:visible .ant-modal-header').first()
      if (await hostHeader.count()) {
        await hostHeader.click({ position: { x: 4, y: 4 }, timeout: 3000 }).catch(() => {})
      } else {
        await dismiss()
      }
      await page.waitForTimeout(320)
    } else if (!keepOverlay) {
      await dismiss()
    }
    if (!(await locator.count())) {
      await dumpOnce(label)
      results.push({ label, ok: false, detail: '控件不存在' })
      return
    }
    await locator.first().click({ timeout: 5000 })
    await page.waitForTimeout(550)
    const popups = await openPopups()
    const usable = popups.filter((item) => item.hitInside)
    if (usable.length === 1) results.push({ label, ok: true, detail: `${usable[0].cls} ${usable[0].size}` })
    else results.push({ label, ok: false, detail: `可用浮层 ${usable.length} 个：${JSON.stringify(popups)}` })
  } catch (error) {
    results.push({ label, ok: false, detail: `点击失败/异常：${String(error.message).split('\n')[0].slice(0, 130)}` })
  }
}

/** 只断言"点下去有反应"，用于开关、按钮这类本来就不弹浮层的控件。 */
const checkInteractive = async (label, locator, { keepOverlay = false } = {}) => {
  try {
    if (!keepOverlay) await dismiss()
    if (!(await locator.count())) {
      results.push({ label, ok: false, detail: '控件不存在' })
      return
    }
    await locator.first().click({ timeout: 5000 })
    await page.waitForTimeout(400)
    results.push({ label, ok: true, detail: '可点击' })
  } catch (error) {
    results.push({ label, ok: false, detail: `点击失败：${String(error.message).split('\n')[0].slice(0, 130)}` })
  }
}

/** 连续点两个控件：第二个点开后必须只剩它一个浮层。 */
const checkSequence = async (label, first, second) => {
  try {
    await dismiss()
    await first.click({ timeout: 5000 })
    await page.waitForTimeout(400)
    await second.click({ timeout: 5000 })
    await page.waitForTimeout(550)
    const usable = (await openPopups()).filter((item) => item.hitInside)
    if (usable.length === 1) results.push({ label, ok: true, detail: `前一个已让位，剩 ${usable[0].cls}` })
    else results.push({ label, ok: false, detail: `同时开着 ${usable.length} 个：${JSON.stringify(usable)}` })
  } catch (error) {
    results.push({ label, ok: false, detail: `点击失败/异常：${String(error.message).split('\n')[0].slice(0, 130)}` })
  }
}

const sidebar = (label) => page.locator('.sidebar-nav-item', { hasText: label }).first()
const goto = async (label, selector) => {
  await dismiss()
  if (label === '创造模式') {
    await gotoStudioViaModeMenu()
    await page.waitForTimeout(1300)
    return
  }
  await sidebar(label).click()
  if (selector) await page.waitForSelector(selector, { timeout: 20000 })
  await page.waitForTimeout(1300)
}

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

// ---------- 对话页 ----------
await sidebar('新建任务').click()
await page.waitForSelector('.chat-stage.is-empty', { timeout: 20000 })
await page.waitForTimeout(1500)
const chips = page.locator('.composer-actions-left .composer-chip')
const chipCount = await chips.count()
const chipLabels = (await chips.allInnerTexts()).map((t) => t.trim())
for (let index = 0; index < chipCount; index += 1) {
  await check(`对话·chip[${index}] ${chipLabels[index]}`, chips.nth(index))
}
for (let index = 0; index + 1 < chipCount; index += 1) {
  await checkSequence(`对话·chip[${index}]→chip[${index + 1}] 只留一个`, chips.nth(index), chips.nth(index + 1))
}
await check('对话·侧边栏工作区选择器', page.locator('.sidebar-footer .ant-select').first())
await check('对话·账号菜单', page.locator('.sidebar-account'))
await check('对话·任务列表更多菜单', page.locator('.ant-conversations-menu-icon').first())
// 通知中心是抽屉，不是浮层，单独断言"能展开"。
await dismiss()
await page.locator('button[aria-label="通知中心"]').click()
await page.waitForTimeout(900)
results.push({
  label: '对话·通知中心抽屉',
  ok: Boolean(await page.locator('.ant-drawer-open').count()),
  detail: (await page.locator('.ant-drawer-open').count()) ? '已展开' : '❌ 没展开',
})
await page.locator('.ant-drawer-open .ant-drawer-close').first().click().catch(() => {})
await page.waitForTimeout(500)

// ---------- 项目看板 ----------
await goto('项目看板', '.page-shell')
const boardSelects = await page.locator('.page-shell .ant-select').count()
for (let index = 0; index < Math.min(boardSelects, 4); index += 1) {
  await check(`看板·Select[${index}]`, page.locator('.page-shell .ant-select').nth(index))
}
// 任务抽屉里的控件：抽屉由卡片点击打开，用类名不确定，改用"点第一张卡片"。
const firstCard = page.locator('.task-card, .ant-card').first()
if (await firstCard.count()) {
  await dismiss()
  await firstCard.click()
  await page.waitForTimeout(1400)
  const drawerOpen = await page.locator('.ant-drawer-open').count()
  if (drawerOpen) {
    const drawerSelects = await page.locator('.ant-drawer-open .ant-select').count()
    for (let index = 0; index < Math.min(drawerSelects, 3); index += 1) {
      await check(`看板·任务抽屉 Select[${index}]`, page.locator('.ant-drawer-open .ant-select').nth(index), { keepOverlay: true, softDismiss: true })
    }
    results.push({ label: '看板·任务抽屉', ok: true, detail: `已展开，Select ${drawerSelects} 个` })
    await page.locator('.ant-drawer-open .ant-drawer-close').first().click().catch(() => {})
    await page.waitForTimeout(500)
  } else {
    results.push({ label: '看板·任务抽屉', ok: false, detail: '点击任务卡片后抽屉没有打开' })
  }
}

// ---------- 通知中心（抽屉，不是浮层） ----------
await goto('插件市场', '.market-page')
await dismiss()
await page.locator('button[aria-label="通知中心"]').click()
await page.waitForTimeout(900)
results.push({
  label: '通知中心抽屉',
  ok: Boolean(await page.locator('.ant-drawer-open').count()),
  detail: (await page.locator('.ant-drawer-open').count()) ? '已展开' : '❌ 没展开',
})
await page.locator('.ant-drawer-open .ant-drawer-close').first().click().catch(() => {})
await page.waitForTimeout(500)

// ---------- 插件市场 ----------
await goto('插件市场', '.market-page')
await checkInteractive('市场·搜索框可聚焦', page.locator('.market-search input'))
await checkInteractive('市场·刷新按钮', page.locator('.market-heading button', { hasText: /刷\s*新/ }).first())

// ---------- 创造模式 ----------
await goto('创造模式', '.studio-page')
// 编辑器里的模型 / 技能 / 图标三个 Select 要能点开
await dismiss()
await page.locator('.studio-page button', { hasText: /新\s*建\s*智\s*能\s*体/ }).first().click().catch(() => {})
await page.waitForTimeout(900)
const studioSelects = await page.locator('.ant-modal-wrap:visible .ant-select').count()
for (let index = 0; index < Math.min(studioSelects, 4); index += 1) {
  await check(`创造模式·编辑器 Select[${index}]`, page.locator('.ant-modal-wrap:visible .ant-select').nth(index), { keepOverlay: true, softDismiss: true })
}
await page.keyboard.press('Escape').catch(() => {})
await page.waitForTimeout(500)

// ---------- 团队成员 ----------
await goto('团队成员', '.page-shell')
const addMember = page.locator('.page-heading button').filter({ hasText: /添\s*加\s*成\s*员/ }).first()
await dismiss()
if (await addMember.count()) {
  await addMember.click()
  try {
    await page.waitForSelector('.ant-modal-wrap:visible', { timeout: 8000 })
    await page.waitForTimeout(700)
    await check('团队·添加成员弹窗 角色 Select', page.locator('.ant-modal-wrap:visible .ant-select').first(), { keepOverlay: true })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
  } catch {
    results.push({ label: '团队·添加成员弹窗 角色 Select', ok: false, detail: '弹窗没打开' })
  }
} else {
  results.push({ label: '团队·添加成员弹窗 角色 Select', ok: false, detail: '找不到「添加成员」按钮（可能是只读角色）' })
}

// ---------- 汇报智能体 / 经营助手 ----------
for (const [label, selector] of [['汇报智能体', '.report-page'], ['经营助手', '.business-page']]) {
  await goto(label, selector)
  const selects = await page.locator(`${selector} .ant-select`).count()
  for (let index = 0; index < Math.min(selects, 4); index += 1) {
    await check(`${label}·Select[${index}]`, page.locator(`${selector} .ant-select`).nth(index))
  }
  const buttons = await page.locator(`${selector} .ant-btn`).count()
  results.push({ label: `${label}·可交互按钮数`, ok: true, detail: `${buttons} 个 ant-btn，Select ${selects} 个` })
}

// ---------- 设置面板 ----------
const openSettings = async () => {
  await dismiss()
  await page.locator('.sidebar-account').click()
  await page.waitForTimeout(700)
  await page.locator('.ant-dropdown-menu-item:visible', { hasText: /^设置$/ }).first().click()
  await page.waitForSelector('.settings-layout', { timeout: 15000 })
  await page.waitForTimeout(600)
}
const settingsSection = async (label) => {
  await openSettings()
  await page.locator('.settings-nav-item', { hasText: label }).first().click()
  await page.waitForTimeout(600)
}

await settingsSection('通用')
// 语言不再是"带下拉箭头却点不动的 Select"，而是纯文本；断言它确实没有假控件。
results.push({
  label: '设置·通用 语言（应为静态文本，没有假下拉）',
  ok: (await page.locator('.settings-section').filter({ hasText: '通用' }).locator('.ant-select').count()) === 0,
  detail: '语言行只读',
})

await settingsSection('浏览器')
await check('设置·浏览器 默认浏览器 Select', page.locator('.settings-section').filter({ hasText: 'AI 任务默认浏览器' }).locator('.ant-select').first(), { keepOverlay: true })
await checkInteractive('设置·浏览器 内置浏览器开关', page.locator('.settings-section').filter({ hasText: '内置浏览器' }).locator('.ant-switch').first(), { keepOverlay: true })

await settingsSection('权限审批')
await checkInteractive('设置·权限审批 常规任务档位', page.locator('[data-testid="permission-regular"] .settings-mode').first(), { keepOverlay: true })
await checkInteractive('设置·权限审批 自动化任务档位', page.locator('[data-testid="permission-automation"] .settings-mode').first(), { keepOverlay: true })

await settingsSection('规则与记忆')
await checkInteractive('设置·规则与记忆 记忆开关', page.locator('.settings-section').filter({ hasText: '记忆 Beta' }).locator('.ant-switch').first(), { keepOverlay: true })

await settingsSection('模型')
await checkInteractive('设置·模型 测试按钮', page.locator('.settings-model').first().locator('button').last(), { keepOverlay: true })

await settingsSection('用量管理')
await checkInteractive('设置·用量 区间切换', page.locator('.settings-section .ant-segmented-item').first(), { keepOverlay: true })

console.log('\n================ 全站下拉体检 ================')
for (const item of results) console.log(`${item.ok ? 'PASS' : 'FAIL'}  ${item.label} — ${item.detail}`)
const broken = results.filter((item) => !item.ok)
console.log(`\n共 ${results.length} 项，失败 ${broken.length} 项`)
for (const item of broken) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
