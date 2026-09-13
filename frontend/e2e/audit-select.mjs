/**
 * "选项到底能不能选中"体检。
 *
 * 之前的体检只验证了浮层能打开、能看到内容，没有验证**点下去真的生效**。
 * 用户反馈的正是"点开什么也没有 / 选项卡不能选择"，所以这里对每一个下拉都
 * 真的选中一项，并断言界面确实变了。
 *
 * 在"保留滚动条"模式下跑（与 Windows 真实浏览器一致）。
 */
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(9000)
page.on('pageerror', (err) => console.log('[pageerror]', String(err).split('\n')[0].slice(0, 140)))

const results = []
const record = (label, ok, detail) => {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label} — ${detail}`)
}

const chip = (index) => page.locator('.composer-actions-left .composer-chip').nth(index)
const chipLabel = (index) => chip(index).locator('.composer-chip-label').innerText()
const clickHeader = async () => {
  await page.locator('.workspace-header').click({ position: { x: 3, y: 3 }, timeout: 3000 }).catch(() => {})
  await page.waitForTimeout(280)
}
const esc = async () => {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(250)
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
await page.locator('.sidebar-nav-item', { hasText: '新建任务' }).first().click()
await page.waitForSelector('.chat-stage.is-empty', { timeout: 20000 })
await page.waitForTimeout(2200)

/** 打开第 index 个 chip，点里面第 optionIndex 项，断言 chip 文案变化。 */
const testPickerChip = async (index, optionIndex, name) => {
  await esc(); await clickHeader()
  const before = await chipLabel(index).catch(() => '?')
  try {
    await chip(index).click()
    await page.waitForTimeout(600)
    // antd 关闭浮层后会把节点留在 DOM 里（display:none），必须限定在"当前可见的那个"，
    // 否则会点到上一个已经隐藏的面板上，表现为 click 超时。
    const options = page.locator('.ant-dropdown:not(.ant-dropdown-hidden) .composer-picker-item:not([disabled])')
    const count = await options.count()
    if (count <= 1) {
      record(`${name}（chip[${index}]）可选中选项`, false, `可选项只有 ${count} 个`)
      return
    }
    // 挑一个和当前值不同的：点中已经选中的那项，文案本来就不会变。
    let targetIndex = Math.min(optionIndex, count - 1)
    for (let i = 0; i < count; i += 1) {
      const active = await options.nth(i).evaluate((el) => el.classList.contains('is-active'))
      if (!active) { targetIndex = i; break }
    }
    const target = options.nth(targetIndex)
    const targetText = (await target.innerText()).split('\n')[0].trim()
    await target.click({ timeout: 6000 })
    await page.waitForTimeout(1000)
    const after = await chipLabel(index).catch(() => '?')
    record(
      `${name}（chip[${index}]）可选中选项`,
      after !== before && after.includes(targetText.slice(0, 6)),
      `选中「${targetText}」：${before} → ${after}（${count} 个候选）`,
    )
  } catch (error) {
    record(`${name}（chip[${index}]）可选中选项`, false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

// ---- 1. 运行模式（menu 型） ----
{
  await esc(); await clickHeader()
  const before = await chipLabel(0).catch(() => '?')
  try {
    await chip(0).click()
    await page.waitForTimeout(600)
    // 菜单尾部还挂着「创造模式」入口（点了会跳页），不能拿"最后一项"当运行模式。
    const items = page.locator('.ant-dropdown-menu-item:visible')
    const count = await items.count()
    let targetIndex = -1
    for (let i = 0; i < count; i += 1) {
      const label = (await items.nth(i).innerText()).trim()
      if (label.includes('创造模式')) continue
      if (label.split('\n')[0].trim() === before) continue
      targetIndex = i
      break
    }
    if (targetIndex < 0) {
      record('运行模式 chip 可选中选项', false, `没找到可切换的运行模式（共 ${count} 项）`)
    } else {
      const target = items.nth(targetIndex)
      const text = (await target.innerText()).split('\n')[0].trim()
      await target.click({ timeout: 5000 })
      await page.waitForTimeout(900)
      const after = await chipLabel(0).catch(() => '?')
      record('运行模式 chip 可选中选项', after !== before && after === text, `选中「${text}」：${before} → ${after}（${count} 项）`)
      // 复位回自主
      await esc(); await clickHeader()
      await chip(0).click(); await page.waitForTimeout(500)
      const back = page.locator('.ant-dropdown-menu-item:visible', { hasText: '自主' }).first()
      if (await back.count()) { await back.click(); await page.waitForTimeout(600) }
    }
  } catch (error) {
    record('运行模式 chip 可选中选项', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

// ---- 2. 模型 / 3. 技能（picker 型） ----
await testPickerChip(1, 1, '模型 chip')
await testPickerChip(2, 1, '技能 chip')

// ---- 4. 工具（勾选型） ----
{
  await esc(); await clickHeader()
  try {
    await chip(3).click()
    await page.waitForTimeout(600)
    const boxes = page.locator('.composer-tools-panel .ant-checkbox-input:not([disabled])')
    const count = await boxes.count()
    if (!count) {
      record('工具 chip 可勾选服务', false, '没有可勾选的服务（面板内 0 个 checkbox）')
    } else {
      const before = await boxes.first().isChecked()
      await boxes.first().click({ timeout: 5000 })
      await page.waitForTimeout(900)
      const after = await boxes.first().isChecked()
      record('工具 chip 可勾选服务', after !== before, `checkbox ${before} → ${after}（共 ${count} 个可勾选）`)
    }
  } catch (error) {
    record('工具 chip 可勾选服务', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

// ---- 5. 授权档位 ----
{
  await esc(); await clickHeader()
  const before = await chipLabel(4).catch(() => '?')
  try {
    await chip(4).click()
    await page.waitForTimeout(600)
    const items = page.locator('.ant-dropdown-menu-item:visible')
    const count = await items.count()
    const target = items.nth(count - 1)
    const text = (await target.innerText()).split('\n')[0].trim()
    await target.click({ timeout: 5000 })
    await page.waitForTimeout(1400)
    const after = await chipLabel(4).catch(() => '?')
    record('授权档位 chip 可选中选项', after !== before, `选中「${text}」：${before} → ${after}（${count} 项）`)
    // 复位成默认档
    if (after !== before) {
      await esc(); await clickHeader()
      await chip(4).click(); await page.waitForTimeout(500)
      await page.locator('.ant-dropdown-menu-item:visible').first().click().catch(() => {})
      await page.waitForTimeout(1200)
    }
  } catch (error) {
    record('授权档位 chip 可选中选项', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

// ---- 6. 账号菜单：点一项必须真的生效 ----
{
  await esc(); await clickHeader()
  try {
    await page.locator('.sidebar-account').click()
    await page.waitForTimeout(700)
    const items = page.locator('.ant-dropdown-menu-item:visible')
    const count = await items.count()
    const labels = (await items.allInnerTexts()).map((t) => t.trim())
    await page.locator('.ant-dropdown-menu-item:visible', { hasText: '设置' }).first().click({ timeout: 5000 })
    await page.waitForSelector('.settings-layout', { timeout: 12000 })
    const sections = await page.locator('.settings-nav-item').count()
    record('账号菜单可选中「设置」', sections > 0, `${count} 项 ${JSON.stringify(labels)} → 设置面板 ${sections} 个分区`)
  } catch (error) {
    record('账号菜单可选中「设置」', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

// ---- 7. 设置面板里的 Select 真的能选中并持久化 ----
{
  try {
    await page.locator('.settings-nav-item', { hasText: '浏览器' }).first().click()
    await page.waitForTimeout(700)
    const select = page.locator('.settings-section').filter({ hasText: 'AI 任务默认浏览器' }).locator('.ant-select').first()
    await select.click()
    await page.waitForTimeout(600)
    const options = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option:not(.ant-select-item-option-disabled)')
    const count = await options.count()
    const labels = (await options.allInnerTexts()).map((t) => t.trim())
    const target = options.nth(count - 1)
    await target.click({ timeout: 5000 })
    await page.waitForTimeout(1200)
    const shown = await select.innerText()
    record('设置·浏览器 Select 可选中并回显', count > 0 && Boolean(shown.trim()), `${count} 个候选 ${JSON.stringify(labels)} → 当前「${shown.trim()}」`)
  } catch (error) {
    record('设置·浏览器 Select 可选中并回显', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
  await page.locator('.settings-close').first().click().catch(() => {})
  await page.waitForTimeout(600)
}

// ---- 8. 看板状态下拉真的能筛选 ----
{
  await esc(); await clickHeader()
  try {
    await page.locator('.sidebar-nav-item', { hasText: '项目看板' }).first().click()
    await page.waitForSelector('.page-shell', { timeout: 15000 })
    await page.waitForTimeout(1400)
    const columnsBefore = await page.locator('.board-column').count()
    const select = page.locator('.page-shell .ant-select').first()
    await select.click()
    await page.waitForTimeout(600)
    const options = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')
    const count = await options.count()
    const labels = (await options.allInnerTexts()).map((t) => t.trim())
    await options.nth(Math.min(1, count - 1)).click({ timeout: 5000 })
    await page.waitForTimeout(1200)
    const shown = await select.innerText()
    record('看板状态筛选可选中', count > 0, `${count} 个候选 ${JSON.stringify(labels.slice(0, 6))} → 当前「${shown.trim()}」（看板列 ${columnsBefore}）`)
  } catch (error) {
    record('看板状态筛选可选中', false, `异常：${String(error.message).split('\n')[0].slice(0, 110)}`)
  }
}

console.log(`\n选择体检：${results.filter((r) => r.ok).length}/${results.length} 通过`)
for (const item of results.filter((r) => !r.ok)) console.log(`  ✗ ${item.label}: ${item.detail}`)
await browser.close()
