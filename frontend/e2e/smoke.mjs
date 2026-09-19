// E2E 冒烟：登录 → Code 工作台渲染 → 看板任务抽屉改状态。
// 完整验收（含真实模型调用与闪烁检测）见 e2e/click-flow.mjs。
// 运行前提：API(8000) 与前端 preview(8899) 或 dev(5173) 已启动。
// 用法：node e2e/smoke.mjs
// 浏览器：优先本机 Edge/Chrome（无需下载浏览器二进制）。
import { chromium } from 'playwright-core'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`)
}

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (err) => errors.push(String(err)))

  // ---- 1. 登录态注入并进入工作台 ----
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
  await page.waitForSelector('.workspace-sider', { timeout: 15000 })
  check('登录后工作台渲染', true)

  // ---- 2. Code 工作台首屏 ----
  await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })
  // 首屏会自动选中最近一个任务：那个任务已经有消息，不会渲染空态主视觉。
  // 两种状态都接受，各自断言自洽，否则这条用例的结果会随历史数据漂移。
  await page.waitForFunction(
    () => {
      const stage = document.querySelector('.chat-stage')
      if (!stage) return false
      return stage.classList.contains('is-empty')
        ? Boolean(document.querySelector('.code-hero h1'))
        : Boolean(document.querySelector('.messages .ant-bubble'))
    },
    null,
    { timeout: 25000 },
  )
  const isEmptyStage = (await page.locator('.chat-stage.is-empty').count()) > 0
  if (isEmptyStage) {
    // 等文案真的出现再断言：主视觉挂载与首帧绘制之间 innerText 可能是空的，
    // 直接读会把"还没画出来"误判成"渲染不对"。
    const heroOk = await page
      .waitForFunction(
        () => /Code with/i.test(document.querySelector('.code-hero h1')?.textContent || ''),
        null,
        { timeout: 15000 },
      )
      .then(() => true)
      .catch(() => false)
    const hero = await page.locator('.code-hero h1').textContent().catch(() => '')
    check('Code 主视觉渲染', heroOk, (hero || '').trim().slice(0, 40))
  } else {
    const bubbleOk = await page
      .waitForFunction(
        () => (document.querySelector('.messages .ant-bubble')?.textContent || '').trim().length > 0,
        null,
        { timeout: 15000 },
      )
      .then(() => true)
      .catch(() => false)
    const firstBubble = await page.locator('.messages .ant-bubble').first().textContent().catch(() => '')
    check('Code 主视觉渲染（已有历史任务，改为校验消息态）', bubbleOk, (firstBubble || '').trim().slice(0, 30))
  }
  check('输入卡与发送按钮渲染', (await page.locator('.composer-card').count()) > 0 && (await page.locator('.composer-send').count()) > 0)
  check('侧边栏无模式切换 tab', (await page.locator('.workspace-sider .ant-segmented').count()) === 0)

  // ---- 3. 项目看板：打开任务抽屉并切换状态 ----
  await page.locator('.sidebar-nav-item', { hasText: '项目看板' }).first().click()
  await page.waitForSelector('.page-shell', { timeout: 15000 })
  const cardCount = await page.locator('.task-card').count()
  if (cardCount) {
    const beforeTitle = await page.locator('.task-card').first().locator('strong').textContent()
    await page.locator('.task-card').first().click()
    await page.waitForSelector('.ant-drawer-open', { timeout: 10000 })
    check('任务抽屉打开', true, beforeTitle || '')

    // 抽屉内第一个下拉是状态：切到"已完成"
    await page.locator('.ant-drawer-open .ant-select').first().click()
    await page.waitForSelector('.ant-select-item-option:visible', { timeout: 5000 })
    await page.locator('.ant-select-item-option:visible', { hasText: '已完成' }).first().click()
    await page.waitForTimeout(1500)
    const drawerText = await page.locator('.ant-drawer-open').innerText()
    check('任务状态切换为已完成', drawerText.includes('已完成'))
    await page.locator('.ant-drawer-open .ant-drawer-close').first().click()
    await page.waitForTimeout(800)
  } else {
    check('看板无可点任务（跳过抽屉用例）', true, 'cardCount=0')
  }

  // ---- 4. 知识库：创建 → 列表可见 → 删除 ----
  const kbTitle = `冒烟知识库 ${Date.now().toString().slice(-5)}`
  await page.locator('.sidebar-nav-item', { hasText: '知识库' }).first().click()
  await page.waitForSelector('.kb-page', { timeout: 15000 })
  check('知识库页面渲染', true)

  await page.locator('.kb-page button', { hasText: '创建文档' }).first().click()
  await page.waitForSelector('.ant-modal-content:visible', { timeout: 10000 })
  await page.locator('.ant-modal-content:visible input').first().fill(kbTitle)
  await page.locator('.ant-modal-content:visible textarea').first().fill('传送带每周需要润滑一次，张力异常时先停机再上报。')
  await page.locator('.ant-modal-content:visible button', { hasText: '创 建' }).first().click()
  await page.waitForSelector(`.kb-card:has-text("${kbTitle}")`, { timeout: 15000 })
  check('新建知识库文档出现在列表', true, kbTitle)

  await page.locator(`.kb-card:has-text("${kbTitle}") button[aria-label^="删除"]`).first().click()
  await page.locator('.ant-popconfirm:visible button', { hasText: '删 除' }).first().click()
  await page.waitForFunction(
    (title) => !document.body.innerText.includes(title),
    kbTitle,
    { timeout: 15000 },
  )
  check('删除知识库文档后列表不再显示', true)

  // ---- 5. 无运行时错误 ----
  check('无运行时错误', errors.length === 0, errors.join('; '))

  const failed = results.filter((r) => !r.ok)
  console.log(`\n== E2E 冒烟：${results.length - failed.length}/${results.length} 通过 ==`)
  process.exitCode = failed.length ? 1 : 0
} finally {
  await browser.close()
}
