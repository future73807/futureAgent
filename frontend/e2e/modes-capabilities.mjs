/**
 * 五档运行模式 + 四大能力的模拟点击验收。
 *
 * 覆盖：对话 / 规划 / 自主 / 目标 / 循环 五档模式，联网搜索（web_search 工具调用链）、
 * MCP（两个服务同时挂载与工具执行）、技能（管理端新建 → 用户端使用）、
 * 创造模式（新建智能体 → 使用 → 删除），以及「规划 → 保存为工作计划 → 批准 → 自主执行」
 * 的完整闭环。
 *
 * 运行前提：
 *   API  127.0.0.1:8000、用户端 5173、管理端 5174、本地替身模型 127.0.0.1:8010
 * 用法：cd frontend && node e2e/modes-capabilities.mjs
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const ADMIN_BASE = process.env.E2E_ADMIN_URL || 'http://localhost:5174'
const MODEL = process.env.E2E_MODEL || 'local-mock'
const RUN_TIMEOUT = Number(process.env.E2E_RUN_TIMEOUT || 120_000)
const OUT = 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const results = []
const record = (label, ok, detail) => {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label} — ${detail}`)
}
const step = async (label, fn) => {
  try {
    await settle().catch(() => {})
    const detail = await fn()
    record(label, true, detail ?? 'ok')
  } catch (error) {
    const message = String(error?.message || error).split('\n')[0].slice(0, 240)
    record(label, false, message)
    await page.screenshot({ path: `${OUT}/fail-${label.replace(/[^\w\u4e00-\u9fa5]+/g, '_').slice(0, 40)}.png` }).catch(() => {})
  }
}

const browser = await chromium.launch({
  channel: process.env.E2E_CHANNEL || 'msedge',
  headless: true,
  ignoreDefaultArgs: ['--hide-scrollbars'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(20_000)
const consoleErrors = []
page.on('pageerror', (err) => consoleErrors.push(String(err).split('\n')[0].slice(0, 160)))
page.on('console', (msg) => {
  if (msg.type() !== 'error') return
  const text = msg.text()
  if (text.includes('401 (Unauthorized)') || text.includes('findDOMNode')) return
  consoleErrors.push(text.slice(0, 160))
})

const shot = (name) => page.screenshot({ path: `${OUT}/modes-${name}.png` }).catch(() => {})
const sidebarNav = (text) => page.locator('.sidebar-nav-item', { hasText: text }).first()
const modeChip = () => page.locator('.composer-actions-left .composer-chip').nth(0)
const modelChip = () => page.locator('.composer-actions-left .composer-chip').nth(1)
// 切页时旧页面会保留到新页面就绪，同名字符串可能同时命中两处；统一取可见的那个。
const vis = (selector) => page.locator(`${selector}:visible`).last()

/** 收掉可能残留的浮层：上一步失败留下的弹窗会挡住后面所有点击。 */
const settle = async () => {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(150)
  if (await page.locator('.settings-layout').count()) {
    await page.locator('.settings-close').first().click({ timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(300)
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const wraps = page.locator('.ant-modal-wrap:visible')
    if (!(await wraps.count())) break
    const cancel = wraps.last().locator('.ant-modal-footer button', { hasText: /取消|关闭/ }).first()
    if (await cancel.count()) await cancel.click({ timeout: 3000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(300)
  }
  const drawer = page.locator('.ant-drawer-open')
  if (await drawer.count()) {
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(300)
  }
}

const dropdownItem = (text) => page.locator('.ant-dropdown-menu-item:visible', { hasText: text }).first()

const pickMode = async (label) => {
  await modeChip().click()
  await page.waitForSelector('.composer-mode-menu .ant-dropdown-menu-item', { timeout: 10_000 })
  await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: label }).first().click()
  await page.waitForTimeout(500)
}

const pickModel = async (modelName) => {
  await modelChip().click()
  const panel = vis('.composer-picker-panel')
  await panel.waitFor({ timeout: 10_000 })
  await panel.locator('input').fill(modelName)
  await page.waitForTimeout(400)
  const option = panel.locator('.composer-picker-item').first()
  await option.waitFor({ timeout: 8_000 })
  await option.click()
  await page.waitForTimeout(400)
  return (await modelChip().innerText()).trim()
}

/** 勾选工具面板里指定的 MCP 服务（面板显示的是服务的展示名，不是内部名）。 */
const pickTools = async (patterns) => {
  const chip = page.locator('.composer-actions-left .composer-chip').nth(3)
  await chip.click()
  const panel = page.locator('.composer-tools-panel')
  await panel.waitFor({ timeout: 10_000 })
  await panel.locator('.composer-tools-row').first().waitFor({ timeout: 10_000 })
  const rows = await panel.locator('.composer-tools-row').all()
  const picked = []
  for (const row of rows) {
    const text = (await row.innerText()).split('\n')[0].trim()
    if (patterns.some((pattern) => pattern.test(text))) {
      const box = row.locator('.ant-checkbox-input')
      if (await box.isDisabled()) throw new Error(`工具服务不可用：${text}`)
      if (!(await box.isChecked())) await box.check()
      picked.push(text)
    }
  }
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  if (!picked.length) {
    const labels = (await panel.locator('.composer-tools-row').allInnerTexts()).map((t) => t.split('\n')[0]).join(' / ')
    throw new Error(`未匹配到工具服务（面板现有：${labels}）`)
  }
  return picked.join(' + ')
}

const sendChat = async (text) => {
  await page.locator('.composer-input textarea').fill(text)
  await page.locator('.composer-send').click()
}

/** 等最后一条助手气泡真正有内容。 */
const waitAssistant = async (timeout = RUN_TIMEOUT) => {
  await page.waitForFunction(
    () => {
      const bubbles = [...document.querySelectorAll('.messages .ant-bubble')]
      const last = bubbles[bubbles.length - 1]
      return Boolean(last && (last.innerText || '').trim().length > 0 && !last.querySelector('.ant-bubble-loading'))
    },
    null,
    { timeout },
  )
  const bubbles = await page.locator('.messages .ant-bubble').allInnerTexts()
  return bubbles[bubbles.length - 1].trim().replace(/\s+/g, ' ')
}

/** 选 antd Select：点开 → 选文本匹配的项。 */
const pickSelect = async (scope, placeholder, optionText) => {
  const select = scope.locator('.ant-select', { hasText: placeholder }).first()
  await select.click()
  await page.waitForSelector('.ant-select-dropdown:visible .ant-select-item-option', { timeout: 10_000 })
  const dropdown = page.locator('.ant-select-dropdown:visible').last()
  let option = optionText
    ? dropdown.locator('.ant-select-item-option', { hasText: optionText }).first()
    : dropdown.locator('.ant-select-item-option').first()
  await option.click()
  await page.waitForTimeout(400)
  return (await select.innerText()).trim()
}

// ---------------------------------------------------------------------------
await step('登录并进入工作台', async () => {
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
  await page.waitForSelector('.workspace-sider', { timeout: 20_000 })
  await page.waitForFunction(() => !document.querySelector('.workspace-loading'), null, { timeout: 40_000 })
  return '工作台已渲染'
})

// ---- 技能：管理端新建 → 用户端可见 -----------------------------------------
const SKILL_NAME = `python_demo_guardian_${Date.now().toString().slice(-5)}`
await step('技能：管理端新建技能', async () => {
  const admin = await context.newPage()
  admin.setDefaultTimeout(20_000)
  await admin.goto(ADMIN_BASE, { waitUntil: 'domcontentloaded' })
  await admin.waitForTimeout(2500)
  const email = admin.locator('input[placeholder="name@company.com"]')
  if (await email.count()) {
    await email.fill('admin@futureagent.dev')
    await admin.locator('input[placeholder="请输入登录密码"]').fill('ChangeMe123!')
    await admin.getByRole('button', { name: /进入管理后台|登\s*录/ }).first().click()
  }
  await admin.waitForSelector('.ant-layout-sider', { timeout: 25_000 })
  await admin.locator('.ant-menu-item', { hasText: '技能管理' }).first().click()
  await admin.waitForTimeout(1500)
  await admin.getByRole('button', { name: '新建技能' }).click()
  const modal = admin.locator('.ant-modal-wrap:visible').last()
  await modal.waitFor({ timeout: 10_000 })
  await modal.locator('#skill-name').fill(SKILL_NAME)
  await modal.locator('#skill-description').fill('python-demo 项目的修复与测试规范（联调验收用）')
  await modal.locator('#skill-system-prompt').fill(
    '你是 python-demo 项目的维护者。改动前先读 README 与 tests，只使用标准库；'
    + '修完必须运行 py -m unittest discover -s tests 并汇报结果。',
  )
  await modal.locator('#skill-tools').fill('read_file, list_files, run_project_tests, project_tree')
  // antd 的「确 认」按钮文案带空格，按可访问名匹配不到，直接点弹窗主按钮。
  await modal.locator('.ant-modal-footer button.ant-btn-primary').last().click()
  await admin.waitForTimeout(2500)
  const listed = await admin.locator('.ant-table-row', { hasText: SKILL_NAME }).count()
  if (!listed) throw new Error('技能列表未出现新技能')
  await admin.screenshot({ path: `${OUT}/modes-skill-admin.png` }).catch(() => {})
  await admin.close()
  return `${SKILL_NAME} 已创建`
})

// ---- 看板：建一个验收任务 --------------------------------------------------
const TASK_TITLE = `验收·python-demo 修复 ${Date.now().toString().slice(-4)}`
await step('看板：新建验收任务', async () => {
  await settle()
  await sidebarNav('项目看板').click()
  await page.waitForSelector('.kanban-grid', { timeout: 25_000 })
  await page.waitForTimeout(1500)
  await page.locator('.page-heading').getByRole('button', { name: '新建任务' }).click()
  const box = page.locator('.ant-modal-wrap:visible').last()
  await box.locator('input').first().fill(TASK_TITLE)
  await box.locator('.ant-modal-footer button.ant-btn-primary').click()
  await page.waitForTimeout(2500)
  const grid = await page.locator('.kanban-grid').innerText()
  if (!grid.includes(TASK_TITLE)) throw new Error(`看板未见任务：${grid.replace(/\n/g, ' ').slice(0, 160)}`)
  return TASK_TITLE
})

// ---- 对话模式 --------------------------------------------------------------
await step('对话模式：切换模型为 local-mock 并收到回复', async () => {
  await sidebarNav('新建任务').click()
  await page.waitForSelector('.composer-input textarea', { timeout: 25_000 })
  await page.waitForTimeout(1200)
  const modelLabel = await pickModel(MODEL)
  await pickMode('对话')
  await sendChat('只回复两个字：收到')
  const answer = await waitAssistant()
  if (!answer) throw new Error('助手气泡为空')
  await shot('01-chat')
  return `模型 ${modelLabel}｜回复：${answer.slice(0, 40)}`
})

// ---- 联网搜索（MCP web_search 工具调用链） ---------------------------------
await step('联网搜索：工具调用链走通', async () => {
  const picked = await pickTools([/工作区|联网/])
  await pickMode('自主')
  await sendChat('联网搜索一下 Python 3.12 的新特性，给我三条要点')
  await page.waitForSelector('.tool-trace-card', { timeout: RUN_TIMEOUT })
  // 工具明细在折叠面板里，展开后才能读到工具名。
  const trace = vis('.tool-trace-card')
  await trace.locator('.ant-collapse-header').click({ timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(600)
  const traceText = await trace.innerText()
  if (!traceText.includes('web_search')) throw new Error(`工具轨迹里没有 web_search：${traceText.replace(/\n/g, ' ').slice(0, 140)}`)
  const answer = await waitAssistant()
  await shot('02-websearch')
  return `${picked}｜轨迹：${traceText.replace(/\n/g, ' ').slice(0, 70)}｜回复：${answer.slice(0, 40)}`
})

// ---- 规划模式 → 保存为工作计划 ---------------------------------------------
await step('规划模式：产出计划卡片', async () => {
  await pickMode('规划')
  await sendChat('为工作区里的 python-demo 项目制定一份修复并验证的计划')
  await page.waitForSelector('.plan-card', { timeout: RUN_TIMEOUT })
  const objective = (await page.locator('.plan-card-objective').last().innerText()).trim()
  const steps = await page.locator('.plan-card-steps li').count()
  await shot('03-plan')
  if (!objective) throw new Error('计划卡片没有目标')
  if (steps < 1) throw new Error('计划卡片没有步骤')
  return `目标：${objective.slice(0, 40)}｜${steps} 个步骤`
})

await step('规划模式：保存为工作计划', async () => {
  await page.locator('.plan-card button', { hasText: '保存为工作计划' }).last().click()
  const modal = page.locator('.ant-modal-wrap:visible').last()
  await modal.waitFor({ timeout: 10_000 })
  const select = modal.locator('.ant-select').first()
  await select.click()
  await page.waitForSelector('.ant-select-dropdown:visible .ant-select-item-option', { timeout: 10_000 })
  // 工作项下拉是虚拟列表，新任务常常不在已渲染的窗口里；先输入标题过滤再选第一项。
  await page.keyboard.type(TASK_TITLE, { delay: 15 })
  await page.waitForTimeout(800)
  const dropdown = page.locator('.ant-select-dropdown:visible').last()
  const option = dropdown.locator('.ant-select-item-option').first()
  await option.waitFor({ timeout: 8_000 })
  await option.click({ timeout: 10_000 })
  await page.locator('.ant-select-dropdown:visible').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(400)
  const chosen = (await select.innerText()).trim()
  if (!chosen.includes(TASK_TITLE.slice(0, 8))) throw new Error(`工作项未选中：${chosen || '(空)'}`)
  await modal.locator('.ant-modal-footer button.ant-btn-primary').last().click({ timeout: 15_000 })
  await page.waitForTimeout(2500)
  await shot('04-plan-saved')
  if (await page.locator('.ant-modal-wrap:visible').count()) throw new Error('保存后弹窗未关闭')
  return `已挂到 ${chosen}`
})

// ---- 工作模式：批准 + 自主执行 ---------------------------------------------
await step('工作模式：打开并批准计划', async () => {
  await sidebarNav('项目看板').click()
  await page.waitForSelector('.kanban-grid', { timeout: 25_000 })
  await page.waitForTimeout(1200)
  await page.locator('.task-card', { hasText: TASK_TITLE }).first().click()
  const drawer = page.locator('.ant-drawer-open').last()
  await drawer.waitFor({ timeout: 15_000 })
  await drawer.getByRole('button', { name: '在工作模式中打开' }).click()
  await page.waitForSelector('.work-results, .plan-execution', { timeout: 25_000 })
  await page.waitForTimeout(2000)
  // 回归点：从抽屉点进来必须就是那个任务（此前工作模式会沿用上次选中的任务）。
  const openedTask = (await vis('.project-selector').innerText().catch(() => '')).trim()
  if (!openedTask.includes(TASK_TITLE)) throw new Error(`工作模式未切到目标任务，当前：${openedTask || '(空)'}`)
  const approve = page.getByRole('button', { name: '批准执行' })
  if (await approve.count()) {
    await approve.first().click({ timeout: 15_000 })
    await page.waitForTimeout(2500)
  }
  const content = vis('.workspace-content')
  const pageText = await content.innerText()
  await shot('05-work-approved')
  // 断言必须落在计划本身：卡片标题与提示文案里本来就带「批准」二字，只看关键词会假通过。
  const hasApprovedCard = await page.locator('.plan-execution', { hasText: '已批准的工作计划' }).count()
  const hasSteps = /读取项目结构|编写并运行脚本|汇总结果/.test(pageText)
  if (!/已批准/.test(pageText) || (!hasApprovedCard && !hasSteps)) {
    throw new Error(`计划未进入已批准态（卡片：${hasApprovedCard}，步骤：${hasSteps}）：${pageText.replace(/\n/g, ' ').slice(0, 140)}`)
  }
  return '计划已批准（已批准的工作计划卡片与步骤齐备）'
})

const workPanel = () => page.locator('.work-results', { has: page.locator('.execution-controls') }).first()

/**
 * 在已展开的下拉里点选目标项。
 * 这些下拉不可搜索且用虚拟列表渲染，目标项常常不在当前窗口里，需要边滚边找。
 */
const clickOptionByText = async (pattern) => {
  const dropdown = page.locator('.ant-select-dropdown:visible').last()
  for (let attempt = 0; attempt < 15; attempt += 1) {
    const option = dropdown.locator('.ant-select-item-option', { hasText: pattern }).first()
    if (await option.count()) {
      await option.click({ timeout: 5000 })
      await page.waitForTimeout(400)
      return true
    }
    const scrolled = await dropdown.locator('.rc-virtual-list-holder').evaluate((el) => {
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1) return false
      el.scrollTop += el.clientHeight
      return true
    }).catch(() => false)
    if (!scrolled) break
    await page.waitForTimeout(300)
  }
  return false
}

/** 执行面板里四个下拉的顺序固定：0 计划步骤 / 1 模型 / 2 技能 / 3 MCP 服务。 */
const prepareExecution = async (mode) => {
  const controls = page.locator('.execution-controls').last()
  const selects = controls.locator('.ant-select')
  const open = async (index) => {
    const select = selects.nth(index)
    await select.click()
    await page.waitForSelector('.ant-select-dropdown:visible .ant-select-item-option', { timeout: 10_000 })
    return select
  }
  const stepSelect = await open(0)
  await clickOptionByText(/待执行|执行中|受阻/)
  const modelSelect = await open(1)
  if (!(await clickOptionByText(MODEL))) throw new Error(`模型下拉里找不到 ${MODEL}`)
  const modelLabel = (await modelSelect.innerText()).trim()
  if (!modelLabel.includes(MODEL.slice(0, 6))) throw new Error(`模型未选中 ${MODEL}：${modelLabel}`)
  const skillSelect = await open(2)
  if (!(await clickOptionByText(/python_demo/))) throw new Error('技能下拉里找不到 python_demo 技能')
  const skillLabel = (await skillSelect.innerText()).trim()
  await open(3)
  await clickOptionByText(/工作区|联网/)
  await clickOptionByText(/python/i)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  await controls.locator('[aria-label="选择运行模式"]').getByText(mode, { exact: true }).click()
  await page.waitForTimeout(500)
  return { modelLabel, skillLabel, step: (await stepSelect.innerText()).trim() }
}

await step('自主模式：执行计划步骤并调用 MCP 工具', async () => {
  await prepareExecution('自主')
  await page.getByRole('button', { name: /执行选中步骤/ }).first().click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(
    () => {
      const cards = [...document.querySelectorAll('.work-results')]
        .filter((card) => card.querySelector('.execution-controls'))
      return cards.some((card) => /已完成|执行失败|已取消/.test(card.innerText))
    },
    null,
    { timeout: RUN_TIMEOUT },
  )
  const body = await workPanel().innerText()
  await shot('06-agent-exec')
  if (/执行失败/.test(body)) throw new Error(`执行失败：${body.replace(/\n/g, ' ').slice(0, 160)}`)
  return body.replace(/\n/g, ' ').slice(0, 160)
})

await step('目标模式：给定目标与达成标准后受监督迭代', async () => {
  await prepareExecution('目标')
  await page.locator('[aria-label="目标"]').fill('让 python-demo 的单元测试全部通过')
  await page.locator('[aria-label="达成标准或停止条件"]').fill('py -m unittest discover -s tests 全部通过')
  await page.getByRole('button', { name: /执行选中步骤/ }).first().click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(
    () => {
      const cards = [...document.querySelectorAll('.work-results')]
        .filter((card) => card.querySelector('.execution-controls'))
      return cards.some((card) => /已完成|执行失败|已取消/.test(card.innerText))
    },
    null,
    { timeout: RUN_TIMEOUT },
  )
  const iterations = await page.locator('.execution-iterations').innerText().catch(() => '')
  await shot('07-goal')
  const body = await workPanel().innerText()
  if (/执行失败/.test(body)) throw new Error(`执行失败：${body.replace(/\n/g, ' ').slice(0, 160)}`)
  return iterations ? iterations.replace(/\n/g, ' ').slice(0, 120) : body.replace(/\n/g, ' ').slice(0, 120)
})

await step('循环模式：按停止条件反复迭代', async () => {
  await prepareExecution('循环')
  await page.locator('[aria-label="达成标准或停止条件"]').fill('README 已补充平均金额的口径说明')
  await page.getByRole('button', { name: /执行选中步骤/ }).first().click()
  await page.waitForTimeout(1500)
  await page.waitForFunction(
    () => {
      const cards = [...document.querySelectorAll('.work-results')]
        .filter((card) => card.querySelector('.execution-controls'))
      return cards.some((card) => /已完成|执行失败|已取消/.test(card.innerText))
    },
    null,
    { timeout: RUN_TIMEOUT },
  )
  const iterations = await page.locator('.execution-iterations').innerText().catch(() => '')
  await shot('08-loop')
  const body = await workPanel().innerText()
  if (/执行失败/.test(body)) throw new Error(`执行失败：${body.replace(/\n/g, ' ').slice(0, 160)}`)
  return iterations ? iterations.replace(/\n/g, ' ').slice(0, 120) : body.replace(/\n/g, ' ').slice(0, 120)
})

// ---- 计划 + 自主：真的把缺陷改掉 -------------------------------------------
await step('计划+自主闭环：执行修复步骤并写入工作区文件', async () => {
  const controls = page.locator('.execution-controls').last()
  const selects = controls.locator('.ant-select')
  await selects.nth(0).click()
  await page.waitForSelector('.ant-select-dropdown:visible .ant-select-item-option', { timeout: 10_000 })
  if (!(await clickOptionByText(/修复|修改|实现|改动/))) {
    await page.keyboard.press('Escape')
    throw new Error('计划里没有可执行的修复步骤（计划只在复现步停下了）')
  }
  await controls.locator('[aria-label="选择运行模式"]').getByText('自主', { exact: true }).click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: /执行选中步骤/ }).first().click()
  await page.waitForFunction(
    () => {
      const cards = [...document.querySelectorAll('.work-results')]
        .filter((card) => card.querySelector('.execution-controls'))
      return cards.some((card) => /执行失败|已取消/.test(card.innerText))
        || cards.some((card) => /已完成/.test(card.innerText))
    },
    null,
    { timeout: RUN_TIMEOUT },
  )
  const panel = workPanel()
  // 执行记录里的工具明细在折叠面板内，展开后才能读到工具名（与对话页同一套组件）。
  for (const header of await panel.locator('.tool-trace-card .ant-collapse-header').all()) {
    await header.click({ timeout: 3000 }).catch(() => {})
  }
  await page.waitForTimeout(600)
  const text = (await panel.innerText()).split('\n').join(' ')
  await shot('12-agent-delivery')
  if (/执行失败|客户端已断开/.test(text)) throw new Error(`修复步骤执行失败：${text.slice(0, 200)}`)
  const wrote = /write_file|edit_file/.test(text)
  if (!wrote) throw new Error(`执行记录里没有写入类工具调用：${text.slice(0, 240)}`)
  return text.slice(0, 220)
})

// ---- 技能：用户端可见并被使用 ----------------------------------------------
await step('技能：用户端可选择新建的技能', async () => {
  await sidebarNav('新建任务').click()
  await page.waitForSelector('.composer-input textarea', { timeout: 25_000 })
  await page.waitForTimeout(1200)
  await pickModel(MODEL)
  const chip = page.locator('.composer-actions-left .composer-chip').nth(2)
  await chip.click()
  const panel = vis('.composer-picker-panel')
  await panel.waitFor({ timeout: 10_000 })
  await panel.locator('input').fill('python_demo_guardian')
  await page.waitForTimeout(500)
  const item = panel.locator('.composer-picker-item').first()
  await item.waitFor({ timeout: 8_000 })
  const label = (await item.innerText()).trim()
  await item.click()
  await page.waitForTimeout(500)
  await shot('09-skill')
  return `技能 chip：${label}`
})

// ---- 创造模式 --------------------------------------------------------------
const AGENT_NAME = `验收智能体${Date.now().toString().slice(-4)}`
await step('创造模式：新建智能体', async () => {
  await modeChip().click()
  await page.waitForSelector('.composer-mode-menu .ant-dropdown-menu-item', { timeout: 10_000 })
  await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
  await page.waitForSelector('.studio-page, .agent-studio', { timeout: 20_000 })
  await page.waitForTimeout(1200)
  const createBtn = page.getByRole('button', { name: /新建智能体|创建智能体/ }).first()
  await createBtn.click()
  const modal = page.locator('.ant-modal-wrap:visible').last()
  await modal.waitFor({ timeout: 10_000 })
  const inputs = modal.locator('input')
  await inputs.first().fill(AGENT_NAME)
  const textareas = modal.locator('textarea')
  await textareas.first().fill('你是验收用的自建智能体，回答必须先说一句“验收智能体就绪”。')
  await modal.locator('.ant-modal-footer button.ant-btn-primary').click()
  await page.waitForTimeout(2500)
  const cards = await page.locator('.studio-card', { hasText: AGENT_NAME }).count()
  if (!cards) throw new Error(`智能体卡片未出现（studio-card 数：${await page.locator('.studio-card').count()}）`)
  await shot('10-create-mode')
  return AGENT_NAME
})

await step('创造模式：使用智能体并发消息', async () => {
  // 兜底：卡片不在当前页时再从运行模式菜单进一次创造模式。
  if (!(await page.locator('.studio-card', { hasText: AGENT_NAME }).count())) {
    await modeChip().click()
    await page.waitForSelector('.composer-mode-menu .ant-dropdown-menu-item', { timeout: 10_000 })
    await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
    await page.waitForSelector('.studio-card', { timeout: 20_000 })
    await page.waitForTimeout(1200)
  }
  // 切页时旧页面会保留在 DOM 里，卡片可能在隐藏的那份上，这里只认可见的。
  const card = page.locator('.studio-card:visible', { hasText: AGENT_NAME }).first()
  await page.locator('.ant-message').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
  await card.scrollIntoViewIfNeeded().catch(() => {})
  const useBtn = card.getByRole('button', { name: /使\s*用/ }).first()
  try {
    await useBtn.click({ timeout: 15_000 })
  } catch (error) {
    const total = await page.locator('.studio-card').count()
    const shown = await page.locator('.studio-card:visible').count()
    throw new Error(`「使用」点不动（卡片 可见 ${shown}/共 ${total}）：${String(error.message || error).slice(0, 80)}`)
  }
  await page.waitForTimeout(2500)
  if (!(await page.locator('.composer-input textarea').count())) {
    const nav = await page.locator('.sidebar-nav-item.is-active').innerText().catch(() => '(未知)')
    const body = (await vis('.workspace-content').innerText().catch(() => '')).replace(/\n/g, ' ').slice(0, 120)
    throw new Error(`「使用」后未回到对话页（当前导航：${nav.replace(/\n/g, ' ')}｜内容：${body}）`)
  }
  const composerText = await page.locator('.chat-stage').innerText()
  await pickModel(MODEL)
  await sendChat('自我介绍一下')
  const answer = await waitAssistant()
  await shot('11-agent-used')
  if (!answer) throw new Error('智能体对话没有回复')
  return `提示条${composerText.includes(AGENT_NAME) ? '含' : '不含'}智能体名｜回复：${answer.slice(0, 40)}`
})

// ---- 收尾：清掉本轮造出来的智能体与技能 --------------------------------------
await step('清理：删除验收智能体', async () => {
  if (!(await page.locator('.studio-card', { hasText: AGENT_NAME }).count())) {
    await modeChip().click()
    await page.waitForSelector('.composer-mode-menu .ant-dropdown-menu-item', { timeout: 10_000 })
    await page.locator('.composer-mode-menu .ant-dropdown-menu-item', { hasText: '创造' }).first().click()
    await page.waitForSelector('.studio-card', { timeout: 20_000 })
    await page.waitForTimeout(1200)
  }
  const card = page.locator('.studio-card:visible', { hasText: AGENT_NAME }).first()
  await card.getByRole('button', { name: /删\s*除/ }).first().click({ timeout: 10_000 })
  const confirm = page.locator('.ant-popover:visible, .ant-popconfirm:visible').last()
  await confirm.getByRole('button', { name: /删\s*除/ }).first().click({ timeout: 8000 })
  await page.waitForTimeout(2000)
  if (await page.locator('.studio-card', { hasText: AGENT_NAME }).count()) throw new Error('智能体未删除')
  return `${AGENT_NAME} 已删除`
})

await step('清理：删除验收技能', async () => {
  const admin = await context.newPage()
  admin.setDefaultTimeout(20_000)
  await admin.goto(ADMIN_BASE, { waitUntil: 'domcontentloaded' })
  await admin.waitForTimeout(2500)
  const email = admin.locator('input[placeholder="name@company.com"]')
  if (await email.count()) {
    await email.fill('admin@futureagent.dev')
    await admin.locator('input[placeholder="请输入登录密码"]').fill('ChangeMe123!')
    await admin.getByRole('button', { name: /进入管理后台/ }).first().click()
  }
  await admin.waitForSelector('.ant-layout-sider', { timeout: 25_000 })
  await admin.locator('.ant-menu-item', { hasText: '技能管理' }).first().click()
  await admin.waitForTimeout(1500)
  const row = admin.locator('.ant-table-row', { hasText: SKILL_NAME }).first()
  if (!(await row.count())) { await admin.close(); return '本轮技能已不在列表中' }
  await row.getByRole('button', { name: /删\s*除/ }).first().click()
  await admin.locator('.ant-popconfirm button.ant-btn-primary, .ant-popover button.ant-btn-primary').first().click({ timeout: 8000 })
  await admin.waitForTimeout(2000)
  const left = await admin.locator('.ant-table-row', { hasText: SKILL_NAME }).count()
  await admin.close()
  if (left) throw new Error('技能未删除')
  return `${SKILL_NAME} 已删除`
})

// ---- 收尾 ------------------------------------------------------------------
await step('无未预期的运行时错误', async () => {
  const unexpected = consoleErrors.filter(
    (text) =>
      !/Failed to load resource: the server responded with a status of 4\d\d/.test(text)
      && !/\[antd:/.test(text)          // antd 的弃用提示不是运行时错误
      && !/deprecated/i.test(text),
  )
  if (unexpected.length) throw new Error(unexpected.slice(0, 3).join(' | '))
  return `0 条（已过滤 401、antd 弃用提示与第三方告警）`
})

const passed = results.filter((item) => item.ok).length
console.log(`\n== 模式与能力验收：${passed}/${results.length} 通过 ==`)
for (const item of results.filter((entry) => !entry.ok)) console.log(`失败：${item.label} — ${item.detail}`)
await browser.close()
