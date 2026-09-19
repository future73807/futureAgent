/**
 * 模拟点击全流程验收。
 *
 * 目标：把用户端当成一个真实用户来点一遍——登录、切页、建项目、建任务、改配置、
 * 发消息、搜索、改主题、退出——任何一步点不动、或内容区闪一下都算失败。
 *
 * 运行前提：
 *   API  : python -m uvicorn main:app --host 127.0.0.1 --port 8000
 *   前端 : cd frontend && npm run dev        （默认 http://localhost:5173）
 *          或 npm run build && npx vite preview --port 8899
 * 用法：
 *   node e2e/click-flow.mjs
 *   E2E_BASE_URL=http://localhost:8899 node e2e/click-flow.mjs
 *
 * 浏览器：优先本机 Edge/Chrome（无需下载浏览器二进制）。
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const EMAIL = process.env.E2E_EMAIL || 'admin@futureagent.dev'
const PASSWORD = process.env.E2E_PASSWORD || 'ChangeMe123!'
// 真实模型调用可能较慢（推理模型尤其），单独给一个宽松上限。
const REPLY_TIMEOUT = Number(process.env.E2E_REPLY_TIMEOUT || 180_000)
const SHOT_DIR = 'e2e/failures'
// 看板任务标题在「新建任务」步骤里生成，归档步骤要用同一个。
let archiveTaskTitle = ''

const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(15000)
mkdirSync(SHOT_DIR, { recursive: true })

// 控制台错误里有两类是环境噪音，不作为失败项：
//   - 未登录时的 /auth/refresh 401（首屏本来就没有会话标记）
//   - antd/React 的 findDOMNode 弃用提示（第三方组件库内部实现）
const consoleErrors = []
page.on('console', (msg) => {
  if (msg.type() !== 'error') return
  const text = msg.text()
  if (text.includes('401 (Unauthorized)')) return
  if (text.includes('findDOMNode')) return
  consoleErrors.push(text)
})
page.on('pageerror', (error) => consoleErrors.push(String(error)))

/** 收掉可能残留的浮层。上一步失败留下的弹窗会遮挡后续所有点击，必须先清干净。 */
const settle = async () => {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(120)
  // 设置面板没有 footer，"取消/关闭"按钮不存在，Escape 也可能被输入框吃掉；
  // 它残留下来会挡住后续每一次点击，所以显式点右上角关闭。
  if (await page.locator('.settings-layout').count()) {
    await page.locator('.settings-close').first().click({ timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(400)
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const wraps = page.locator('.ant-modal-wrap:visible')
    if (!(await wraps.count())) break
    const cancel = page.locator('.ant-modal-wrap:visible .ant-modal-footer button', { hasText: /取消|关闭/ }).first()
    if (await cancel.count()) await cancel.click({ timeout: 3000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(350)
  }
  const drawers = page.locator('.ant-drawer-open')
  if (await drawers.count()) {
    await page.locator('.ant-drawer-open .ant-drawer-close').first().click({ timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(300)
  }
  // 下拉是 body 级浮层，Esc 不一定收起；点一下画布空白处更稳。
  if (await page.locator('.ant-dropdown:visible, .composer-picker-panel:visible, .composer-tools-panel:visible').count()) {
    await page.locator('.workspace-header').click({ position: { x: 4, y: 4 }, timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(250)
  }
}

let failedSteps = 0
const step = async (name, fn) => {
  try {
    await settle()
    const detail = await fn()
    check(name, true, detail ?? '')
  } catch (error) {
    failedSteps += 1
    const message = String(error?.message || error)
    // 失败现场留一张截图：选择器猜错和功能真的坏了，看图的判断成本最低。
    const shot = `${SHOT_DIR}/${String(failedSteps).padStart(2, '0')}-${name.replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 40)}.png`
    await page.screenshot({ path: shot }).catch(() => {})
    const firstLine = message.split('\n')[0]
    const log = message.split('\n').map((line) => line.trim()).filter((line) => /resolved to|intercepts pointer|not stable|not visible|outside of the viewport/.test(line))
    check(name, false, `${[firstLine, ...log].join(' ⏐ ').replace(/\u001b\[\d+m/g, '').slice(0, 240)} [${shot}]`)
  }
}

const sidebarNav = (label) => page.locator('.sidebar-nav-item', { hasText: label }).first()
const dropdownItem = (label) => page.locator('.ant-dropdown-menu-item:visible', { hasText: label }).first()
// antd 会在"恰好两个汉字"的按钮文案里插一个空格（"归 档"、"取 消"），
// 按可访问名精确匹配会全部落空，因此统一用允许空格的宽松正则。
const btn = (text) => new RegExp(text.split('').join('\\s*'))
const heading = () => page.locator('.page-heading, .settings-page, .kb-page').first()
const modal = (titleText) => page.locator('.ant-modal-content:visible', { hasText: titleText })
const confirmModal = (titleText, okText) => {
  const box = page.locator('.ant-modal-confirm:visible, .ant-modal-content:visible').filter({ hasText: titleText }).first()
  return { box, ok: box.getByRole('button', { name: btn(okText) }).first() }
}
/** 任务列表里针对某一条目的"更多"菜单：hover 后点省略号图标 */
const openTaskMenu = async (index = 0) => {
  await settle()
  const item = page.locator('.sidebar-conversations .ant-conversations-item').nth(index)
  await item.waitFor({ timeout: 10000 })
  await item.scrollIntoViewIfNeeded()
  await item.hover()
  await page.waitForTimeout(250)
  await item.locator('.ant-conversations-menu-icon').click({ timeout: 8000 })
  await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
}

/** chips 用的是受控 popupRender 面板，必须先确保上一个面板已收起再点。 */
const openChipPanel = async (index, panelSelector) => {
  await settle()
  const chip = page.locator('.composer-actions-left .composer-chip').nth(index)
  await chip.click({ timeout: 8000 })
  await page.waitForSelector(`${panelSelector}:visible`, { timeout: 8000 })
  return page.locator(`${panelSelector}:visible`).first()
}

/**
 * 点开侧边栏账号菜单。
 * 菜单可能正处于上一次交互的收起动画里，那一刻点下去会被"吃掉"（DOM 里还留着
 * 正在淡出的节点，但里面已经没有可读文本）。这里等到真正出现带文字的菜单项为止，
 * 不行就再点一次。
 */
/** 打开账号菜单，并在同一次求值里把菜单项读出来。
 *
 * 分成「等」和「读」两次调用会踩到竞态：工作区数据刷新会重挂头像区、
 * 连带收起正在展开的下拉，于是等待刚刚通过、读取却拿到空数组。
 */
const readAccountMenu = async () => {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(200)
    await page.locator('.sidebar-account').click()
    const handle = await page.waitForFunction(
      () => {
        const items = [...document.querySelectorAll('.ant-dropdown-menu-item')]
          .filter((el) => el.offsetParent !== null)
          .map((el) => (el.innerText || '').trim())
        return items.some((item) => item.includes('工作区设置')) ? items : null
      },
      null,
      { timeout: 6000 },
    ).catch(() => null)
    if (handle) return await handle.jsonValue()
    await page.waitForTimeout(400)
  }
  return []
}

const openAccountMenu = async () => {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    // 菜单可能已经开着（再点一下反而收起），先确保是关闭状态。
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(200)
    await page.locator('.sidebar-account').click()
    try {
      await page.waitForFunction(
        () => [...document.querySelectorAll('.ant-dropdown-menu-item')]
          .some((el) => el.offsetParent !== null && (el.innerText || '').includes('工作区设置')),
        null,
        { timeout: 4000 },
      )
      return
    } catch {
      await page.waitForTimeout(400)
    }
  }
  throw new Error('账号菜单未展开')
}

try {
  // ================= A. 认证 =================
  await step('打开首页显示登录表单', async () => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.auth-card', { timeout: 20000 })
    return 'auth-card 渲染'
  })

  await step('错误口令被拒绝且停留在登录页', async () => {
    await page.getByLabel('工作邮箱').fill(EMAIL)
    await page.getByLabel('密码').fill('WrongPassword123')
    await page.getByRole('button', { name: '登录工作区' }).click()
    await page.waitForTimeout(1800)
    if (!(await page.locator('.auth-card').count())) throw new Error('错误口令竟然进入了工作台')
    return '仍停留在登录页'
  })

  await step('正确口令进入工作台（首屏加载 < 3s）', async () => {
    await page.getByLabel('密码').fill(PASSWORD)
    const started = Date.now()
    await page.getByRole('button', { name: '登录工作区' }).click()
    await page.waitForSelector('.workspace-sider', { timeout: 25000 })
    await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })
    const elapsed = Date.now() - started
    if (elapsed > 3000) throw new Error(`首屏耗时 ${elapsed}ms，超过 3s`)
    return `工作台已渲染（${elapsed}ms）`
  })

  // ================= B. 只有 Code 一种形态 =================
  await step('侧边栏没有多模式切换 tab', async () => {
    const segmented = await page.locator('.workspace-sider .ant-segmented').count()
    const tabs = await page.locator('.workspace-sider .ant-tabs-nav').count()
    const sidebarText = await page.locator('.workspace-sider').innerText()
    const leaked = ['Design', 'Work'].filter((word) => new RegExp(`(^|\\s)${word}(\\s|$)`).test(sidebarText))
    if (segmented || tabs) throw new Error(`侧边栏存在模式切换器：segmented=${segmented} tabs=${tabs}`)
    if (leaked.length) throw new Error(`侧边栏出现模式名：${leaked.join(',')}`)
    return 'segmented=0 tabs=0'
  })

  // ================= C. Code 工作台首屏 =================
  await step('主区渲染 Code 主视觉与输入卡', async () => {
    // 历史任务多的时候首屏会自动选中最近一个、直接进消息态；只有空任务才有
    // 主视觉。两种状态都接受，但各自必须自洽（空态有主标题，消息态有气泡），
    // 否则说明渲染卡在了中间态。
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
    const isEmpty = await page.locator('.chat-stage.is-empty').count()
    let detail = '消息态：输入卡（已有历史任务）'
    if (isEmpty) {
      const title = (await page.locator('.code-hero h1').innerText()).trim()
      if (!/Code with/i.test(title)) throw new Error(`主标题异常：${title}`)
      detail = `空态：${title}`
    }
    if (!(await page.locator('.composer-card').count())) throw new Error('缺少输入卡')
    if (!(await page.locator('.composer-send').count())) throw new Error('缺少发送按钮')
    if (!(await page.locator('.code-dock-tools').count())) throw new Error('缺少右下角浮动工具条')
    return detail
  })

  await step('四个快捷动作可点击并写入输入框', async () => {
    // 首屏会自动选中最近一个任务；那个任务已经有消息，空态快捷动作不会渲染。
    // 先建一个空任务，把 Code 工作台的首屏状态稳定下来。
    await sidebarNav('新建任务').click()
    // 等模型列表落地再断言：模型还在探测时输入卡仍在变，空态/消息态会短暂
    // 来回切换，此时直接数元素会数到 0（截图里其实四个都渲染着）。
    await page.waitForFunction(
      () => /glm|gpt|claude|ollama|gemini|longcat/i.test(document.querySelectorAll('.composer-actions-left .composer-chip')[1]?.innerText || ''),
      null,
      { timeout: 30000 },
    )
    await page.waitForSelector('.chat-stage.is-empty', { timeout: 20000 })
    const hero = (await page.locator('.code-hero h1').innerText()).trim()
    if (!/Code with/i.test(hero)) throw new Error(`空态主标题异常：${hero}`)
    await page.waitForFunction(
      () => document.querySelectorAll('.chat-stage.is-empty .code-quick-action').length === 4,
      null,
      { timeout: 20000 },
    )
    const actions = page.locator('.chat-stage.is-empty .code-quick-action')
    const count = await actions.count()
    if (count !== 4) throw new Error(`快捷动作数量为 ${count}`)
    for (let index = 0; index < count; index += 1) {
      await actions.nth(index).click()
      await page.waitForTimeout(150)
      const value = await page.locator('.composer-input textarea').inputValue()
      if (!value.trim()) throw new Error(`第 ${index + 1} 个快捷动作没有写入内容`)
      await page.locator('.composer-input textarea').fill('')
    }
    return '4 个动作均写入成功'
  })

  // 部署默认模型由服务端配置决定（MODEL_PROFILES_JSON / DEFAULT_MODEL），
  // 断言必须跟着它走：写死某个型号的用例换一次供应商就会误报。
  const deploymentDefaultModel = await page.evaluate(async () => {
    const token = sessionStorage.getItem('futureagent.access_token')
    const res = await fetch('/api/v1/models', { headers: { Authorization: `Bearer ${token}` } })
    const data = await res.json()
    return String(data.default_model || '')
  })

  await step(`模型列表不含任何 GPT 模型，且默认落在 ${deploymentDefaultModel}`, async () => {
    // 模型探针要真实打一次供应商（约 2s），先等 chip 上出现真实模型名。
    const chip = page.locator('.composer-actions-left .composer-chip').nth(1)
    await page.waitForFunction(
      () => /glm|gpt|claude|ollama|gemini|longcat/i.test(document.querySelectorAll('.composer-actions-left .composer-chip')[1]?.innerText || ''),
      null,
      { timeout: 30000 },
    )
    const label = (await chip.innerText()).trim()
    if (/gpt/i.test(label)) throw new Error(`默认模型仍是 GPT 系列：${label}`)
    if (!label.toLowerCase().includes(deploymentDefaultModel.toLowerCase())) {
      throw new Error(`默认模型不是 ${deploymentDefaultModel}：${label}`)
    }

    const panel = await openChipPanel(1, '.composer-picker-panel')
    const options = (await panel.locator('.composer-picker-item').allInnerTexts()).map((text) => text.trim())
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    const gptEntries = options.filter((text) => /gpt/i.test(text))
    if (gptEntries.length) throw new Error(`模型列表仍提供 GPT 模型：${gptEntries.join(',')}`)
    return `默认 ${label}；可选 ${options.length} 个，无 GPT 系列`
  })

  await step(`历史选过 gpt-4o 的偏好会自动回退到 ${deploymentDefaultModel}`, async () => {
    // 用户上一版把 gpt-4o 存在本地。模型下架后必须自动回退，不能发出去才发现失败。
    await page.evaluate(() => {
      localStorage.setItem('futureagent.composer', JSON.stringify({
        mode: 'agent', modelId: 'gpt-4o', skillName: 'default', mcpServers: [], maxIterations: 5,
      }))
    })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.chat-stage', { timeout: 25000 })
    await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })
    const chip = page.locator('.composer-actions-left .composer-chip').nth(1)
    await page.waitForFunction(
      () => /glm|gpt|claude|ollama|gemini|longcat/i.test(document.querySelectorAll('.composer-actions-left .composer-chip')[1]?.innerText || ''),
      null,
      { timeout: 30000 },
    )
    const label = (await chip.innerText()).trim()
    if (!label.toLowerCase().includes(deploymentDefaultModel.toLowerCase())) {
      throw new Error(`未回退到 ${deploymentDefaultModel}：${label}`)
    }
    return `gpt-4o → ${label}`
  })


  // ================= D. 导航切页 + 闪烁探针 =================
  await step('安装闪烁探针（逐帧采样内容区）', async () => {
    await page.evaluate(() => {
      window.__flicker = { blank: 0, loading: 0, frames: 0 }
      const tick = () => {
        const el = document.querySelector('.workspace-content')
        window.__flicker.frames += 1
        if (!el || !(el.innerText || '').trim()) window.__flicker.blank += 1
        if (document.querySelector('.workspace-loading')) window.__flicker.loading += 1
        window.__flickerRaf = requestAnimationFrame(tick)
      }
      tick()
    })
    return 'probe on'
  })

  const routes = [
    ['项目看板', '.page-shell', '项目看板'],
    ['插件市场', '.market-page', '插件市场'],
    ['知识库', '.kb-page', '知识库'],
    ['团队成员', '.page-shell', '团队成员'],
  ]
  for (const [label, selector, title] of routes) {
    await step(`切到「${label}」并渲染`, async () => {
      await sidebarNav(label).click()
      await page.waitForSelector(selector, { timeout: 20000 })
      const text = await page.locator(selector).first().innerText()
      if (!text.includes(title)) throw new Error(`页面未包含标题「${title}」`)
      return text.split('\n')[0].slice(0, 30)
    })
  }

  await step('插件市场：插件页签列出真实 MCP 服务', async () => {
    await sidebarNav('插件市场').click()
    await page.waitForSelector('.market-card', { timeout: 20000 })
    // 卡片主标题与副标题都是 ant-typography，取第一个才是名字。
    const names = await page.locator('.market-card').evaluateAll((cards) => cards.map(
      (card) => (card.querySelector('.market-card-title .ant-typography')?.textContent || '').trim(),
    ))
    if (!names.length) throw new Error('插件列表为空')
    // 卡片必须来自后端 MCP 清单，而不是前端写死的展示数据。
    const servers = await page.evaluate(async () => {
      const res = await fetch('/api/v1/mcp/servers', {
        headers: {
          Authorization: `Bearer ${sessionStorage.getItem('futureagent.access_token')}`,
          'X-Workspace-ID': sessionStorage.getItem('futureagent.workspace_id'),
        },
      })
      return (await res.json()).servers.map((item) => item.name)
    })
    for (const name of servers) {
      if (!names.includes(name)) throw new Error(`MCP 服务 ${name} 没有出现在插件市场`)
    }
    return `${names.length} 个插件：${names.join(', ')}`
  })

  await step('插件市场：搜索可过滤', async () => {
    const total = await page.locator('.market-card').count()
    await page.locator('.market-search input').fill('zzz-不存在的插件')
    await page.waitForTimeout(400)
    if (await page.locator('.market-card').count() !== 0) throw new Error('搜索没有过滤掉不匹配的插件')
    await page.locator('.market-search input').fill('')
    await page.waitForTimeout(400)
    const restored = await page.locator('.market-card').count()
    if (restored !== total) throw new Error(`清空搜索后没有恢复：${restored}/${total}`)
    return `${total} → 0 → ${restored}`
  })

  await step('插件市场：技能页签含分类与精选', async () => {
    await page.locator('.market-toolbar .ant-segmented-item', { hasText: '技能' }).click()
    await page.waitForSelector('.market-card', { timeout: 15000 })
    const categories = (await page.locator('.market-category').allInnerTexts()).map((t) => t.trim())
    for (const expected of ['全部', '精选', '研发工具']) {
      if (!categories.includes(expected)) throw new Error(`缺少分类「${expected}」：${categories.join('/')}`)
    }
    const featured = await page.locator('.market-featured-card').count()
    if (!featured) throw new Error('没有精选技能')
    // 分类筛选必须真的收窄结果
    const all = await page.locator('.market-card').count()
    await page.locator('.market-category', { hasText: '研发工具' }).first().click()
    await page.waitForTimeout(400)
    const filtered = await page.locator('.market-card').count()
    if (filtered === 0 || filtered >= all) throw new Error(`分类筛选无效：${all} → ${filtered}`)
    await page.locator('.market-category', { hasText: '全部' }).first().click()
    await page.waitForTimeout(300)
    return `${categories.length} 个分类，精选 ${featured} 个，筛选 ${all} → ${filtered}`
  })

  await step('插件市场：安装状态写入工作区偏好并可回读', async () => {
    await page.locator('.market-toolbar .ant-segmented-item', { hasText: '插件' }).click()
    await page.waitForSelector('.market-card', { timeout: 15000 })
    const card = page.locator('.market-card').first()
    const name = (await card.locator('.market-card-title .ant-typography').first().innerText()).trim()
    const readButton = () => card.locator('.market-card-actions button').first().innerText()
    const before = (await readButton()).replace(/\s/g, '')
    await card.locator('.market-card-actions button').first().click()
    // 按钮文案会在"安装 ⇄ 已安装"之间翻转，等它真的变了再断言。
    await page.waitForFunction(
      (previous) => {
        const button = document.querySelector('.market-card .market-card-actions button')
        return button && button.textContent.replace(/\s/g, '') !== previous
      },
      before,
      { timeout: 15000 },
    )
    await page.waitForTimeout(900)
    const after = (await readButton()).replace(/\s/g, '')
    const stored = await page.evaluate(async () => {
      const res = await fetch('/api/v1/workspaces/' + sessionStorage.getItem('futureagent.workspace_id') + '/preferences', {
        headers: {
          Authorization: `Bearer ${sessionStorage.getItem('futureagent.access_token')}`,
          'X-Workspace-ID': sessionStorage.getItem('futureagent.workspace_id'),
        },
      })
      return (await res.json()).preferences.installed_plugins
    })
    if ((after === '已安装') !== stored.includes(name)) {
      throw new Error(`偏好与实际不一致：按钮=${after}，服务端=${JSON.stringify(stored)}`)
    }
    await card.locator('.market-card-actions button').first().click()
    await page.waitForFunction(
      (previous) => {
        const button = document.querySelector('.market-card .market-card-actions button')
        return button && button.textContent.replace(/\s/g, '') !== previous
      },
      after,
      { timeout: 15000 },
    )
    await page.waitForTimeout(900)
    return `${name}：${before} → ${after} → 复位`
  })

  await step('插件市场：使用技能会带到对话输入卡', async () => {
    await page.locator('.market-toolbar .ant-segmented-item', { hasText: '技能' }).click()
    await page.waitForSelector('.market-card', { timeout: 15000 })
    const card = page.locator('.market-card').filter({ has: page.locator('.market-card-title', { hasText: 'coder' }) }).first()
    await card.locator('.market-card-actions button').first().click()
    await page.waitForSelector('.chat-stage', { timeout: 20000 })
    // 技能 chip 显示的是技能名本身（除 default 显示为"通用助手"）。
    await page.waitForFunction(
      () => (document.querySelectorAll('.composer-actions-left .composer-chip')[2]?.innerText || '').trim() === 'coder',
      null,
      { timeout: 20000 },
    )
    const chip = (await page.locator('.composer-actions-left .composer-chip').nth(2).innerText()).trim()
    // 复位回通用助手，避免影响后续步骤
    await openChipPanel(2, '.composer-picker-panel')
    await page.locator('.composer-picker-panel .composer-picker-item', { hasText: '通用助手' }).first().click()
    await page.waitForTimeout(600)
    return `技能 chip → ${chip}`
  })

  await step('导航反复切换不出现空白帧/加载骨架', async () => {
    for (let round = 0; round < 2; round += 1) {
      for (const [label] of routes) {
        await sidebarNav(label).click()
        await page.waitForTimeout(260)
      }
    }
    const probe = await page.evaluate(() => {
      cancelAnimationFrame(window.__flickerRaf)
      return window.__flicker
    })
    if (probe.blank > 0) throw new Error(`检测到 ${probe.blank}/${probe.frames} 帧内容区为空（闪白）`)
    if (probe.loading > 0) throw new Error(`检测到 ${probe.loading}/${probe.frames} 帧出现整屏加载骨架`)
    return `${probe.frames} 帧全部有内容`
  })

  // ================= E. 看板全流程 =================
  let projectName = ''
  await step('看板：新建项目', async () => {
    projectName = `验收项目${Date.now().toString().slice(-5)}`
    await sidebarNav('项目看板').click()
    await page.waitForSelector('.page-shell', { timeout: 20000 })
    await page.locator('.page-heading').getByRole('button', { name: /新建项目|创建第一个项目/ }).first().click()
    const box = modal('新建项目')
    await box.waitFor({ timeout: 10000 })
    await box.locator('input').first().fill(projectName)
    await box.locator('.ant-modal-footer button.ant-btn-primary').click()
    await page.waitForSelector('.kanban-grid', { timeout: 20000 })
    await page.waitForTimeout(1500)
    // 建完必须自动切到新项目，否则用户会停在旧项目的空看板上。
    const selected = (await page.locator('.project-selector').innerText()).trim()
    if (!selected.includes(projectName)) throw new Error(`看板未切到新项目，当前选中：${selected.replace(/\n/g, ',')}`)
    return `${projectName} 已选中`
  })

  await step('看板：新建任务', async () => {
    await page.locator('.page-heading').getByRole('button', { name: '新建任务' }).click()
    const box = modal('新建任务')
    await box.waitFor({ timeout: 10000 })
    archiveTaskTitle = `验收归档任务${Date.now().toString().slice(-5)}`
    await box.locator('input').first().fill(archiveTaskTitle)
    await box.locator('.ant-modal-footer button.ant-btn-primary').click()
    await page.waitForSelector('.task-card', { timeout: 20000 })
    const titles = await page.locator('.task-card strong').allInnerTexts()
    if (!titles.some((item) => item.includes(archiveTaskTitle))) throw new Error(`看板未出现任务：${titles.join(',')}`)
    return `${titles.length} 张卡片`
  })

  await step('看板：任务抽屉改状态', async () => {
    await page.locator('.task-card', { hasText: archiveTaskTitle }).first().click()
    await page.waitForSelector('.ant-drawer-open', { timeout: 10000 })
    await page.locator('.ant-drawer-open .ant-select').first().click()
    await page.waitForSelector('.ant-select-item-option:visible', { timeout: 8000 })
    await page.locator('.ant-select-item-option:visible', { hasText: '进行中' }).first().click()
    await page.waitForTimeout(1500)
    const text = await page.locator('.ant-drawer-open').innerText()
    if (!text.includes('进行中')) throw new Error('状态未切换')
    return '状态 → 进行中'
  })

  await step('看板：日历视图切换', async () => {
    await page.locator('.board-filters .ant-segmented-item', { hasText: '日历' }).click()
    await page.waitForSelector('.calendar-grid', { timeout: 10000 })
    await page.locator('.board-filters .ant-segmented-item', { hasText: '看板' }).click()
    await page.waitForSelector('.kanban-grid', { timeout: 10000 })
    return '看板 ⇄ 日历'
  })

  await step('看板：归档工作项并可从「显示已归档」恢复', async () => {
    await sidebarNav('项目看板').click()
    await page.waitForSelector('.kanban-grid', { timeout: 25000 })
    await page.waitForTimeout(1200)
    const card = page.locator('.task-card', { hasText: archiveTaskTitle }).first()
    await card.waitFor({ timeout: 15000 })
    await card.click()
    const drawer = page.locator('.ant-drawer-open').last()
    await drawer.waitFor({ timeout: 15000 })
    await drawer.getByRole('button', { name: /归\s*档/ }).first().click()
    await page.locator('.ant-popconfirm:visible, .ant-popover:visible').last()
      .getByRole('button', { name: /归\s*档/ }).first().click()
    await page.waitForTimeout(2500)
    // 归档后默认视图里必须消失
    if (await page.locator('.task-card', { hasText: archiveTaskTitle }).count()) {
      throw new Error('归档后卡片仍在默认看板上')
    }
    // 打开「显示已归档」应能找回，并在抽屉里恢复
    await page.locator('.board-filters', { hasText: '显示已归档' }).getByRole('checkbox').check()
    await page.waitForTimeout(2000)
    const archivedCard = page.locator('.task-card.is-archived', { hasText: archiveTaskTitle }).first()
    await archivedCard.waitFor({ timeout: 15000 })
    await archivedCard.click()
    await page.locator('.ant-drawer-open').last().getByRole('button', { name: /恢复工作项/ }).click({ timeout: 10000 })
    // 抽屉没关之前会挡住看板上的开关，先等它消失。
    await page.locator('.ant-drawer-open').last().waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(2000)
    await page.locator('.board-filters', { hasText: '显示已归档' }).getByRole('checkbox').uncheck()
    await page.waitForTimeout(1500)
    if (!(await page.locator('.task-card', { hasText: archiveTaskTitle }).count())) {
      throw new Error('恢复后卡片没有回到看板')
    }
    return `${archiveTaskTitle} 归档 → 隐藏 → 显示已归档 → 恢复`
  })

  // ================= F. 任务（对话）全流程 =================
  await step('侧边栏「新建任务」创建条目', async () => {
    const before = await page.locator('.sidebar-conversations .ant-conversations-item').count()
    await sidebarNav('新建任务').click()
    await page.waitForSelector('.chat-stage', { timeout: 15000 })
    await page.waitForFunction(
      (count) => document.querySelectorAll('.sidebar-conversations .ant-conversations-item').length > count,
      before,
      { timeout: 15000 },
    )
    return `${before} → ${await page.locator('.sidebar-conversations .ant-conversations-item').count()} 条任务`
  })

  const taskTitle = `验收任务${Date.now().toString().slice(-5)}`
  await step('任务列表：重命名', async () => {
    await openTaskMenu(0)
    await dropdownItem('重命名').click()
    const box = modal('重命名任务')
    await box.waitFor({ timeout: 10000 })
    await box.locator('input').first().fill(taskTitle)
    await box.locator('.ant-modal-footer button.ant-btn-primary').click()
    await page.waitForTimeout(1500)
    const text = await page.locator('.sidebar-conversations').innerText()
    if (!text.includes(taskTitle)) throw new Error('列表未出现新标题')
    return taskTitle
  })

  await step('任务列表：归档后可从「已归档任务」恢复', async () => {
    await openTaskMenu(0)
    await dropdownItem('归档').click()
    const confirm = confirmModal('归档任务', '归档')
    await confirm.box.waitFor({ timeout: 10000 })
    await confirm.ok.click()
    await page.waitForTimeout(1800)
    if ((await page.locator('.sidebar-conversations').innerText()).includes(taskTitle)) throw new Error('归档后仍在列表')

    await page.locator('.sidebar-archived-button').click()
    const drawer = page.locator('.ant-drawer-open', { hasText: '已归档任务' })
    await drawer.waitFor({ timeout: 10000 })
    await drawer.getByRole('button', { name: btn('恢复') }).first().click()
    await page.waitForTimeout(1800)
    await page.locator('.ant-drawer-open .ant-drawer-close').first().click()
    await page.waitForTimeout(600)
    if (!(await page.locator('.sidebar-conversations').innerText()).includes(taskTitle)) throw new Error('恢复后未回到列表')
    return '归档 → 恢复'
  })

  // ================= G. 输入卡配置项 =================
  await step('运行模式 chip 切换为「规划」', async () => {
    await page.locator('.sidebar-conversations .ant-conversations-item').first().click()
    await page.waitForTimeout(1000)
    const chip = page.locator('.composer-actions-left .composer-chip').first()
    await chip.click()
    await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
    await dropdownItem('规划').click()
    await page.waitForTimeout(600)
    const label = await chip.innerText()
    if (!label.includes('规划')) throw new Error(`chip 文案未更新：${label}`)
    return '对话 → 规划'
  })

  await step('模型 chip 可搜索并切换', async () => {
    const chip = page.locator('.composer-actions-left .composer-chip', { hasText: /glm|gpt|claude|ollama|gemini|longcat|模型/i }).first()
    const panel = await openChipPanel(1, '.composer-picker-panel')
    await panel.locator('input').fill('glm')
    await page.waitForTimeout(400)
    const option = panel.locator('.composer-picker-item').first()
    await option.waitFor({ timeout: 8000 })
    const optionText = (await option.innerText()).trim()
    await option.click()
    await page.waitForTimeout(600)
    const label = (await chip.innerText()).trim()
    if (!label) throw new Error('模型 chip 为空')
    return `${optionText} → ${label}`
  })

  await step('技能 chip 可搜索并切换', async () => {
    const chip = page.locator('.composer-actions-left .composer-chip').nth(2)
    const panel = await openChipPanel(2, '.composer-picker-panel')
    const before = (await chip.innerText()).trim()
    await panel.locator('.composer-picker-item').nth(1).click()
    await page.waitForTimeout(600)
    return `${before} → ${(await chip.innerText()).trim()}`
  })

  await step('工具 chip 面板可勾选', async () => {
    const chip = page.locator('.composer-actions-left .composer-chip').nth(3)
    const panel = await openChipPanel(3, '.composer-tools-panel')
    const row = panel.locator('.composer-tools-row').first()
    await row.waitFor({ timeout: 8000 })
    const name = (await row.innerText()).split('\n')[0]
    const box = row.locator('.ant-checkbox-input')
    if (await box.isDisabled()) throw new Error(`工具服务不可用：${name}`)
    await box.check()
    await page.waitForTimeout(600)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    const label = await chip.innerText()
    if (!/工具\s*·\s*1/.test(label)) throw new Error(`工具 chip 未反映选中：${label}`)
    return `${name} 已勾选`
  })

  await step('授权档位 chip 改档并回读', async () => {
    const chip = page.locator('button[aria-label="工具授权档位"]')
    await chip.click()
    await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
    await dropdownItem('自动审批').click()
    await page.waitForTimeout(1800)
    const label = await chip.innerText()
    if (!label.includes('自动审批')) throw new Error(`档位未切换：${label}`)
    // 还原成默认权限，避免污染后续手工验收
    await chip.click()
    await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
    await dropdownItem('默认权限').click()
    await page.waitForTimeout(1800)
    if (!(await chip.innerText()).includes('默认权限')) throw new Error('档位未还原')
    return '默认 → 自动审批 → 默认'
  })

  await step('附件上传链路可用', async () => {
    const before = await page.locator('.chat-attachment-list .ant-btn').count()
    await page.locator('.composer-card input[type=file]').first().setInputFiles({
      name: '验收附件.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('futureAgent 附件链路验收', 'utf8'),
    })
    await page.waitForTimeout(3000)
    const text = await page.locator('.chat-attachment-strip').innerText().catch(() => '')
    const after = await page.locator('.chat-attachment-list .ant-btn').count()
    if (after <= before && !text.includes('附件')) throw new Error('附件未出现在对话附件区')
    return text.replace(/\n/g, ' ').slice(0, 40)
  })

  // ================= H. 真实发送 + 流式回复 + 持久化 =================
  await step('发送消息并收到模型流式回复', async () => {
    // 上一步把运行模式切到了「规划」，规划模式按契约返回结构化计划 JSON。
    // 这里切回「自主」再提问，验证的是用户最常见的那条路径：问一句、答一句。
    const modeChip = page.locator('.composer-actions-left .composer-chip').first()
    await modeChip.click()
    await page.waitForSelector('.ant-dropdown-menu-item:visible', { timeout: 8000 })
    await dropdownItem('自主').click()
    await page.waitForTimeout(500)

    await page.locator('.composer-input textarea').fill('只回复两个字：收到')
    await page.locator('.composer-send').click()
    // 先把两个气泡（用户 + 助手占位）等出来，再等助手正文真正落地。
    // 只等气泡数量会立刻满足——占位气泡的正文还是空的。
    await page.waitForSelector('.messages .ant-bubble', { timeout: 15000 })
    await page.waitForFunction(
      () => document.querySelectorAll('.messages .ant-bubble').length >= 2,
      null,
      { timeout: 30000 },
    )
    await page.waitForFunction(
      () => {
        const bubbles = [...document.querySelectorAll('.messages .ant-bubble')]
        const last = bubbles[bubbles.length - 1]
        return Boolean(last && (last.innerText || '').trim().length > 0 && !last.querySelector('.ant-bubble-loading'))
      },
      null,
      { timeout: REPLY_TIMEOUT },
    )
    const bubbles = await page.locator('.messages .ant-bubble').allInnerTexts()
    const answer = bubbles[bubbles.length - 1].trim().replace(/\s+/g, ' ')
    if (!answer) throw new Error('助手气泡为空')
    if (/操作未完成|未能完成本次请求/.test(answer)) throw new Error(`模型返回失败：${answer.slice(0, 60)}`)
    if (/^\{"objective"/.test(answer)) throw new Error(`自主模式不应返回计划 JSON：${answer.slice(0, 60)}`)
    return answer.slice(0, 60)
  })

  await step('刷新后对话仍然存在（消息已持久化）', async () => {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.chat-stage', { timeout: 25000 })
    await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 30000 })
    await page.waitForTimeout(1500)
    const bubbles = await page.locator('.messages .ant-bubble').count()
    if (bubbles < 2) throw new Error(`刷新后只剩 ${bubbles} 条气泡`)
    return `${bubbles} 条气泡`
  })

  // ================= I. 全局搜索 / 通知 =================
  await step('全局搜索可检索并跳转', async () => {
    await page.locator('.global-search input').fill(taskTitle.slice(0, 4))
    await page.waitForTimeout(1500)
    const option = page.locator('.ant-select-item-option:visible').first()
    await option.waitFor({ timeout: 12000 })
    const text = (await option.innerText()).replace(/\n/g, ' ')
    await option.click()
    await page.waitForTimeout(1200)
    return text.slice(0, 40)
  })

  await step('通知中心抽屉可开合', async () => {
    await page.locator('button[aria-label="通知中心"]').click()
    const drawer = page.locator('.ant-drawer-open', { hasText: '通知中心' })
    await drawer.waitFor({ timeout: 10000 })
    await page.locator('.ant-drawer-open .ant-drawer-close').first().click()
    await page.waitForTimeout(800)
    if (await page.locator('.ant-drawer-open', { hasText: '通知中心' }).count()) throw new Error('抽屉未关闭')
    return '开 → 关'
  })

  // ================= J. 账号菜单 / 设置 / 主题 =================
  await step('账号菜单可打开', async () => {
    const items = await readAccountMenu()
    if (!items.some((item) => item.includes('工作区设置'))) throw new Error(`菜单项异常：[${items.join(' / ')}]`)
    return items.join(' / ').slice(0, 60)
  })

  await step('工作区设置页可打开', async () => {
    await openAccountMenu()
    await dropdownItem('工作区设置').click()
    await page.waitForSelector('.settings-page', { timeout: 20000 })
    const title = await page.locator('.settings-page h2').first().innerText()
    if (!title.includes('工作区设置')) throw new Error(`标题异常：${title}`)
    return title
  })

  // ================= J2. 设置面板 =================
  // 注意：step() 开头的 settle() 会按 Escape 收掉残留浮层，而设置面板本身
  // 就是一个浮层。所以每一步都自己重新打开面板，不要跨步骤依赖它还开着。
  const openSettings = async () => {
    await openAccountMenu()
    await dropdownItem('设置').click()
    await page.waitForSelector('.settings-layout', { timeout: 15000 })
    await page.waitForTimeout(300)
  }
  const gotoSection = async (label) => {
    await page.locator('.settings-nav-item', { hasText: label }).first().click()
    await page.waitForFunction(
      (want) => (document.querySelector('.settings-title')?.textContent || '').trim() === want,
      label,
      { timeout: 10000 },
    )
  }

  await step('设置面板可从账号菜单打开并切换分区', async () => {
    await openSettings()
    const sections = (await page.locator('.settings-nav-item').allInnerTexts()).map((t) => t.trim())
    for (const expected of ['账号', '用量管理', '通用', '权限审批', 'MCP', '模型', '浏览器', '规则与记忆', '关于 futureAgent']) {
      if (!sections.includes(expected)) throw new Error(`缺少分区「${expected}」：${sections.join('/')}`)
    }
    for (const label of ['权限审批', 'MCP', '模型', '浏览器', '规则与记忆', '关于 futureAgent', '账号']) {
      await gotoSection(label)
    }
    return `${sections.length} 个分区，逐个切换正常`
  })

  await step('设置面板：模型分区显示能力标签', async () => {
    await openSettings()
    await gotoSection('模型')
    // 期望的标签由「部署里这个模型的档案」推导，写死会随供应商变化误报。
    const detail = await page.evaluate(async (id) => {
      const token = sessionStorage.getItem('futureagent.access_token')
      const res = await fetch('/api/v1/models', { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      return (data.details || []).find((item) => item.id === id) || null
    }, deploymentDefaultModel)
    const tokenLabel = (value) => (value >= 1_000_000 ? `${value / 1_000_000}M` : `${Math.round(value / 1000)}K`)
    const expected = []
    if (detail?.tool_calling !== false) expected.push('工具调用')
    if (detail?.vision) expected.push('视觉')
    if (detail?.max_input_tokens > 0) expected.push(`上下文 ${tokenLabel(detail.max_input_tokens)}`)
    if (detail?.max_output_tokens > 0) expected.push(`输出上限 ${tokenLabel(detail.max_output_tokens)}`)
    if (!expected.length) throw new Error(`部署档案里没有可断言的能力标签：${JSON.stringify(detail)}`)

    const glm = page.locator('.settings-model').filter({ hasText: deploymentDefaultModel }).first()
    await glm.waitFor({ timeout: 20000 })
    const meta = (await glm.locator('.settings-model-meta').innerText()).replace(/\n/g, ' ')
    for (const label of expected) {
      if (!meta.includes(label)) throw new Error(`能力标签缺少「${label}」：${meta}`)
    }
    // 探测按钮要真的打一次供应商；按钮文案可能被 antd 插空格，用宽松正则。
    await glm.getByRole('button', { name: btn('测试') }).first().click()
    await page.waitForFunction(
      (modelId) => {
        const rows = [...document.querySelectorAll('.settings-model')]
        const target = rows.find((el) => (el.textContent || '').includes(modelId))
        return target && /探测通过|探测失败|失败|不可用|错误/.test(target.textContent || '')
      },
      deploymentDefaultModel,
      { timeout: 120000 },
    )
    const state = (await glm.innerText()).replace(/\s+/g, ' ')
    if (!state.includes('探测通过')) throw new Error(`模型探测未通过：${state.slice(0, 120)}`)
    return `${meta}｜探测通过`
  })

  await step('设置面板：规则可新增与删除', async () => {
    await openSettings()
    await gotoSection('规则与记忆')
    const rule = `验收规则-${Date.now() % 100000}`
    await page.locator('.settings-rule-add input').fill(rule)
    await page.locator('.settings-rule-add').getByRole('button', { name: btn('创建') }).first().click()
    await page.waitForFunction(
      (text) => [...document.querySelectorAll('.settings-rule-list li')].some((el) => el.textContent.includes(text)),
      rule,
      { timeout: 15000 },
    )
    const listed = await page.locator('.settings-rule-list li').count()
    await page.locator('.settings-rule-list li', { hasText: rule }).locator('button').click()
    await page.waitForFunction(
      (text) => ![...document.querySelectorAll('.settings-rule-list li')].some((el) => el.textContent.includes(text)),
      rule,
      { timeout: 15000 },
    )
    const left = await page.locator('.settings-rule-list li').count()
    return `新增后 ${listed} 条 → 删除后 ${left} 条`
  })

  await step('设置面板：记忆与浏览器开关写入工作区偏好', async () => {
    const readPrefs = () => page.evaluate(async () => {
      const res = await fetch('/api/v1/workspaces/' + sessionStorage.getItem('futureagent.workspace_id') + '/preferences', {
        headers: {
          Authorization: `Bearer ${sessionStorage.getItem('futureagent.access_token')}`,
          'X-Workspace-ID': sessionStorage.getItem('futureagent.workspace_id'),
        },
      })
      return (await res.json()).preferences
    })

    await openSettings()
    await gotoSection('规则与记忆')
    const memory = page.locator('.settings-section').filter({ hasText: '记忆 Beta' }).locator('.ant-switch').first()
    const before = await memory.getAttribute('aria-checked')
    const expected = before !== 'true'
    await memory.click()
    await page.waitForTimeout(1200)
    const afterMemory = (await readPrefs()).memory_enabled
    if (afterMemory !== expected) throw new Error(`记忆开关未落库：期望 ${expected}，实际 ${afterMemory}`)
    await memory.click()
    await page.waitForTimeout(1200)

    await gotoSection('浏览器')
    const external = page.locator('.settings-section').filter({ hasText: '外部浏览器' }).locator('.ant-switch').first()
    const externalBefore = await external.getAttribute('aria-checked')
    await external.click()
    await page.waitForTimeout(1200)
    const afterExternal = (await readPrefs()).browser.allow_external
    if (afterExternal !== (externalBefore !== 'true')) {
      throw new Error(`外部浏览器开关未落库：期望 ${externalBefore !== 'true'}，实际 ${afterExternal}`)
    }
    await external.click()
    await page.waitForTimeout(1200)
    return `memory ${before} → ${expected} → 复位；browser.allow_external ${externalBefore} → 复位`
  })

  await step('设置面板：常规任务权限档位落库', async () => {
    await openSettings()
    await gotoSection('权限审批')
    const regular = page.locator('[data-testid="permission-regular"]')
    await regular.waitFor({ timeout: 10000 })
    const modes = (await regular.locator('.settings-mode-label').allInnerTexts()).map((t) => t.trim())
    if (modes.length !== 3) throw new Error(`档位数量异常：${modes.join('/')}`)
    await regular.locator('.settings-mode', { hasText: '自动审批' }).locator('.ant-radio-wrapper').click()
    await page.waitForTimeout(1200)
    const stored = await page.evaluate(async () => {
      const workspaceId = sessionStorage.getItem('futureagent.workspace_id')
      const res = await fetch('/api/v1/workspaces', {
        headers: {
          Authorization: `Bearer ${sessionStorage.getItem('futureagent.access_token')}`,
          'X-Workspace-ID': workspaceId,
        },
      })
      const payload = await res.json()
      return (payload.workspaces || []).find((item) => item.id === workspaceId)?.permission_mode
    })
    if (stored !== 'auto_approve') throw new Error(`常规档位没有落库：${stored}`)
    await regular.locator('.settings-mode', { hasText: '手动审批' }).locator('.ant-radio-wrapper').click()
    await page.waitForTimeout(1200)
    return `${modes.join('/')} → auto_approve → 复位`
  })

  await step('设置面板：用量管理展示真实统计', async () => {
    await openSettings()
    await gotoSection('用量管理')
    await page.waitForSelector('.settings-usage-cell', { timeout: 30000 })
    const cells = (await page.locator('.settings-usage-cell').allInnerTexts()).map((t) => t.replace(/\n/g, '='))
    const rows = await page.locator('.settings-section tbody tr').count()
    if (!rows) throw new Error('用量表没有数据行')
    return `${cells.join(' ')}｜${rows} 个模型`
  })

  await step('设置面板可关闭且不影响当前页面', async () => {
    await openSettings()
    await page.locator('.settings-close').click()
    await page.waitForTimeout(600)
    if (await page.locator('.settings-layout').count()) throw new Error('面板未关闭')
    if (!(await page.locator('.workspace-sider').count())) throw new Error('关闭设置后工作台不见了')
    return '已关闭'
  })

  await step('顶栏主题切换可用（浅 → 深 → 浅）', async () => {
    const toggle = page.locator('button[aria-label="切换深浅色主题"]')
    await toggle.click()
    await page.waitForTimeout(800)
    const dark = await page.evaluate(() => document.documentElement.dataset.theme)
    if (dark !== 'dark') throw new Error(`未切到深色：${dark}`)
    await toggle.click()
    await page.waitForTimeout(800)
    const light = await page.evaluate(() => document.documentElement.dataset.theme)
    if (light !== 'light') throw new Error(`未切回浅色：${light}`)
    return 'light → dark → light'
  })

  await step('刷新按钮可用且不出现整屏骨架', async () => {
    await page.locator('button[aria-label="刷新工作区"]').click()
    await page.waitForTimeout(600)
    const loading = await page.locator('.workspace-loading').count()
    if (loading) throw new Error('刷新时出现整屏骨架')
    await page.waitForTimeout(2500)
    return '静默刷新'
  })

  await step('任务列表：删除任务', async () => {
    await sidebarNav('新建任务').click()
    await page.waitForTimeout(1800)
    const before = await page.locator('.sidebar-conversations .ant-conversations-item').count()
    await openTaskMenu(0)
    await dropdownItem('删除').click()
    const confirm = confirmModal('删除任务', '删除')
    await confirm.box.waitFor({ timeout: 10000 })
    await confirm.ok.click()
    await page.waitForTimeout(2000)
    const after = await page.locator('.sidebar-conversations .ant-conversations-item').count()
    if (after >= before) throw new Error(`删除后条目数未减少：${before} → ${after}`)
    return `${before} → ${after}`
  })

  await step('退出登录回到登录页', async () => {
    await openAccountMenu()
    await dropdownItem('退出登录').click()
    await page.waitForSelector('.auth-card', { timeout: 15000 })
    return '已退出'
  })

  await step('无未预期的运行时错误', async () => {
    if (consoleErrors.length) throw new Error(consoleErrors.slice(0, 3).join(' | ').slice(0, 220))
    return '0 条'
  })
} finally {
  await browser.close()
}

const failed = results.filter((item) => !item.ok)
console.log(`\n== 模拟点击全流程：${results.length - failed.length}/${results.length} 通过 ==`)
if (failed.length) console.log(`失败项：\n${failed.map((item) => ` - ${item.name} — ${item.detail}`).join('\n')}`)
process.exitCode = failed.length ? 1 : 0
