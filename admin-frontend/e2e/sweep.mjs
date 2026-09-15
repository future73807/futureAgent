/**
 * Admin console simulated-click sweep.
 *
 *   cd <admin-frontend> && node e2e/sweep.mjs
 *
 * - logs in through the real login form
 * - discovers the sidebar navigation from the DOM, visits every page and
 *   screenshots it into e2e/screens/
 * - clicks every visible non-destructive button and asserts the UI reacted
 * - destructive actions (delete / revoke / disable / reset password / logout)
 *   are exercised ONLY on throwaway objects created by this run, then cleaned up
 * - collects pageerror / console.error / HTTP>=400 mapped to the page
 * - failure screenshots go into e2e/failures/
 *
 * Requires: vite dev server on :5174 and the API on :8000 (via vite proxy).
 */

import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * playwright-core lives in different node_modules depending on the checkout,
 * so resolve it from the usual suspects instead of a bare import.
 */
async function loadChromium() {
  const candidates = [
    'playwright-core',
    path.join(HERE, '..', 'node_modules', 'playwright-core'),
    path.join(HERE, '..', '..', 'node_modules', 'playwright-core'),
    path.join(HERE, '..', '..', 'frontend', 'node_modules', 'playwright-core'),
  ]
  const errors = []
  for (const c of candidates) {
    const specs = c === 'playwright-core' ? ['playwright-core'] : [`${c}/index.js`, `${c}/index.mjs`]
    for (const s of specs) {
      try {
        const spec = s === 'playwright-core' ? s : pathToFileURL(s).href
        const mod = await import(spec)
        const chromium = mod.chromium || mod.default?.chromium
        if (chromium) return chromium
      } catch (e) {
        errors.push(`${s}: ${String(e.message).split('\n')[0]}`)
      }
    }
  }
  throw new Error(`无法加载 playwright-core\n${errors.join('\n')}`)
}

const chromium = await loadChromium()
const SCREENS = path.join(HERE, 'screens')
const FAILURES = path.join(HERE, 'failures')
const LOG_FILE = path.join(HERE, 'sweep.log')
const JSON_FILE = path.join(HERE, 'last-run.json')

const BASE = process.env.SWEEP_BASE || 'http://localhost:5174/'
const ADMIN_EMAIL = 'admin@futureagent.dev'
const ADMIN_PASSWORD = 'ChangeMe123!'

const RUN_ID = String(Date.now())
const STAMP = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z')

fs.mkdirSync(SCREENS, { recursive: true })
fs.mkdirSync(FAILURES, { recursive: true })

// ---------------------------------------------------------------------------
// bookkeeping
// ---------------------------------------------------------------------------

const stats = { PASS: 0, FAIL: 0, SKIP: 0 }
const passes = []
const failures = []
const skips = []
const observations = []
const visited = []
const consoleErrors = []
const pageErrors = []
const httpErrors = []
const downloads = []
const popups = []

const outLines = []
function log(line) {
  outLines.push(line)
  console.log(line)
}
function pass(pageName, action, evidence) {
  stats.PASS++
  passes.push({ page: pageName, action, evidence })
  log(`PASS ${pageName} :: ${action} — ${evidence}`)
}
function fail(pageName, action, reason, screenshot) {
  stats.FAIL++
  failures.push({ page: pageName, action, reason, screenshot: screenshot || null })
  log(`FAIL ${pageName} :: ${action} — ${reason}${screenshot ? ` [截图 ${screenshot}]` : ''}`)
}
function skip(pageName, action, reason) {
  stats.SKIP++
  skips.push({ page: pageName, action, reason })
  log(`SKIP ${pageName} :: ${action} — ${reason}`)
}
function observe(pageName, action, detail) {
  observations.push({ page: pageName, action, detail })
  log(`OBS  ${pageName} :: ${action} — ${detail}`)
}

const norm = (s) => String(s || '').replace(/\s+/g, '')

let currentPage = 'login'
let reqSeq = 0
let reqTail = ''
let lastDownload = ''
let downloadSeq = 0
let failureShotSeq = 0
let pendingApi = 0
let cleanupPhase = false

// Objects created by this run (only these may be deleted / disabled).
const mine = {
  userEmail: '',
  userName: '',
  userPassword: '',
  workspaceName: '',
  workspaceId: '',
  skills: [],
  policies: [],
}

// ---------------------------------------------------------------------------
// expected (known, non-defect) noise
// ---------------------------------------------------------------------------

const EXPECTED_HTTP = [
  { test: (e) => /\/api\/v1\/models\/.+\/probe$/.test(e.url) && e.status >= 500, note: '模型真实探测：外部模型中继不可用（预期 502，环境已知故障）' },
  { test: (e) => /\/api\/v1\/auth\/(refresh|me)$/.test(e.url) && e.status === 401, note: '首屏恢复会话时无 Cookie，刷新令牌返回 401（预期）' },
]

function expectedHttp(e) {
  for (const rule of EXPECTED_HTTP) if (rule.test(e)) return rule.note
  return null
}

const EXPECTED_CONSOLE = [
  { re: /favicon\.ico/i, note: '开发服务器未提供 favicon.ico，浏览器默认请求 404（与业务功能无关）' },
  { re: /Failed to load resource.*(502|503|504)/i, note: '模型真实探测 502：外部模型中继不可用（环境已知故障）' },
  { re: /401/, urlRe: /\/api\/v1\/auth\/(refresh|me)$/, note: '首屏无 Cookie 时恢复会话返回 401（预期）' },
]

function expectedConsole(c) {
  const blob = `${c.text} ${c.url || ''}`
  for (const rule of EXPECTED_CONSOLE) {
    if (rule.urlRe) {
      if (rule.urlRe.test(c.url || '') && rule.re.test(blob)) return rule.note
    } else if (rule.re.test(blob)) {
      return rule.note
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

function shortErr(e) {
  return String((e && e.message) || e).split('\n')[0].slice(0, 200)
}

function slugOf(label) {
  const map = {
    '平台概览': 'dashboard',
    '用户管理': 'users',
    '工作区': 'workspaces',
    '审计轨迹': 'audit',
    '用量统计': 'usage',
    '模型中心': 'models',
    '技能管理': 'skills',
    'MCP 服务': 'mcp',
    '权限策略': 'policies',
    '运行设置': 'settings',
    '顶栏': 'header',
  }
  if (map[label]) return map[label]
  return norm(label).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'page'
}

async function failureShot(page, label) {
  failureShotSeq++
  const name = `admin-${STAMP}-${slugOf(label)}-${failureShotSeq}.png`
  const abs = path.join(FAILURES, name)
  try {
    await page.screenshot({ path: abs })
  } catch {
    /* keep going */
  }
  return `e2e/failures/${name}`
}

async function pageTitle(page) {
  return page
    .evaluate(() => (document.querySelector('.admin-content .page-heading h2')?.innerText || '').trim())
    .catch(() => '')
}

async function settle(page, ms = 400) {
  await page.waitForTimeout(ms)
}

/** Wait until no /api request is in flight (vite dev server + FastAPI). */
async function waitApiIdle(timeout = 30000) {
  const deadline = Date.now() + timeout
  let idleSince = 0
  while (Date.now() < deadline) {
    if (pendingApi <= 0) {
      if (!idleSince) idleSince = Date.now()
      if (Date.now() - idleSince > 250) return true
    } else {
      idleSince = 0
    }
    await new Promise((r) => setTimeout(r, 100))
  }
  return false
}

async function waitMessagesGone(page, timeout = 4500) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const n = await page
      .evaluate(() =>
        [...document.querySelectorAll('.ant-message-notice')].filter((el) => {
          const r = el.getBoundingClientRect()
          return r.width > 0 && r.height > 0
        }).length,
      )
      .catch(() => 0)
    if (n === 0) return
    await page.waitForTimeout(200)
  }
}

async function settlePage(page, label, timeout = 30000) {
  await page.waitForTimeout(300) // let mount effects fire their requests
  await page
    .waitForFunction(() => !document.querySelector('.admin-content .ant-spin-spinning'), null, { timeout })
    .catch(() => {})
  await waitApiIdle(30000)
  await page.waitForTimeout(450)
  await page
    .waitForFunction(
      (expected) => {
        const t = String(document.querySelector('.admin-content .page-heading h2')?.innerText || '').replace(/\s+/g, '')
        return t === String(expected).replace(/\s+/g, '')
      },
      label,
      { timeout: 8000 },
    )
    .catch(() => {})
  await waitApiIdle(10000)
}

/** A button inside any *visible* dialog / confirm popup (antd uses different footers). */
function dialogButton(page, re) {
  return page
    .locator(
      '.ant-modal-wrap:visible .ant-modal-footer button, .ant-modal-wrap:visible .ant-modal button, .ant-modal-confirm-btns button:visible, .ant-popconfirm-buttons button:visible',
    )
    .filter({ hasText: re })
    .first()
}

async function clickNav(page, label) {
  const items = await page.$$('.admin-navigation .ant-menu-item')
  for (const h of items) {
    const t = await h.innerText().catch(() => '')
    if (norm(t) === norm(label)) {
      await h.click({ timeout: 8000 }).catch(() => {})
      return true
    }
  }
  return false
}

async function ensurePage(page, label) {
  const t1 = await pageTitle(page)
  if (norm(t1) === norm(label)) {
    // a hash navigation may not have re-rendered yet — confirm it is stable
    await page.waitForTimeout(400)
    const t2 = await pageTitle(page)
    if (norm(t2) === norm(label)) return true
  }
  const ok = await clickNav(page, label)
  if (!ok) return false
  await settlePage(page, label)
  return true
}

// ---------------------------------------------------------------------------
// overlay handling
// ---------------------------------------------------------------------------

async function overlayOpen(page) {
  return page
    .evaluate(() => {
      const vis = (el) => {
        if (!el) return false
        const r = el.getBoundingClientRect()
        const st = getComputedStyle(el)
        return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'
      }
      return [...document.querySelectorAll('.ant-modal-wrap, .ant-drawer, .ant-dropdown, .ant-popover, .ant-select-dropdown, .ant-picker-dropdown')].some(vis)
    })
    .catch(() => false)
}

async function closeOverlays(page) {
  for (let i = 0; i < 4; i++) {
    if (!(await overlayOpen(page))) return
    await page.keyboard.press('Escape')
    await page.waitForTimeout(280)
  }
  // fallback: explicit cancel / close buttons
  const cancel = page
    .locator('.ant-modal-footer button, .ant-drawer-footer button, .ant-popconfirm-buttons button')
    .filter({ hasText: /^(取\s*消|关\s*闭|Cancel)$/ })
    .first()
  if (await cancel.isVisible().catch(() => false)) {
    await cancel.click({ timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(300)
  }
  for (let i = 0; i < 2; i++) {
    if (!(await overlayOpen(page))) return
    await page.keyboard.press('Escape')
    await page.waitForTimeout(250)
  }
}

// ---------------------------------------------------------------------------
// button discovery + interaction
// ---------------------------------------------------------------------------

let sweepGen = 0

async function collectButtons(page, { includeOverlay = false, includeChrome = false } = {}) {
  sweepGen++
  const gen = sweepGen
  const handles = await page.$$('button, [role=button], .ant-btn')
  const items = []
  for (const h of handles) {
    const meta = await h
      .evaluate((el, g) => {
        if (el.__sweepGen === g) return null
        el.__sweepGen = g
        if (!el.isConnected) return null
        const r = el.getBoundingClientRect()
        const st = getComputedStyle(el)
        if (r.width < 2 || r.height < 2) return null
        if (st.visibility === 'hidden' || st.display === 'none') return null
        const chrome = el.closest('.admin-header, .admin-sider, .admin-mobile-drawer')
        const overlay = el.closest('.ant-modal-wrap, .ant-drawer, .ant-dropdown, .ant-popover, .ant-tooltip')
        const row = el.closest('.ant-table-tbody tr')
        const raw = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim()
        const cls = el.className || ''
        const isSwitch = el.getAttribute('role') === 'switch' || (typeof cls === 'string' && cls.includes('ant-switch'))
        const disabled =
          el.disabled === true ||
          el.getAttribute('aria-disabled') === 'true' ||
          (typeof cls === 'string' && (cls.includes('ant-btn-disabled') || cls.includes('ant-switch-disabled')))
        const loading = typeof cls === 'string' && cls.includes('ant-btn-loading')
        return {
          name: raw || '(无名称按钮)',
          rowText: row ? row.innerText.replace(/\s+/g, ' ').trim().slice(0, 90) : '',
          chrome: Boolean(chrome),
          overlay: Boolean(overlay),
          disabled,
          loading,
          switch: isSwitch,
          tag: el.tagName.toLowerCase(),
        }
      }, gen)
      .catch(() => null)
    if (!meta) continue
    if (meta.chrome && !includeChrome) continue
    if (!includeOverlay && meta.overlay) continue
    items.push({ handle: h, ...meta })
  }
  const seen = new Map()
  return items.map((it) => {
    const key = `${norm(it.name)}||${it.rowText}`
    const occ = (seen.get(key) || 0) + 1
    seen.set(key, occ)
    return { ...it, key, occurrence: occ }
  })
}

async function findButton(page, key, occurrence) {
  const items = await collectButtons(page, { includeOverlay: true })
  const same = items.filter((i) => i.key === key)
  return same[occurrence - 1] || null
}

async function findByName(page, name, { overlay = true, chrome = false } = {}) {
  const items = await collectButtons(page, { includeOverlay: overlay, includeChrome: chrome })
  return items.find((i) => norm(i.name) === norm(name)) || null
}

async function snapshot(page) {
  return page.evaluate(() => ({
    hash: location.hash,
    rows: document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length,
    textHash: window.__sweepHash(document.querySelector('.admin-content')?.innerText || ''),
    textLen: (document.querySelector('.admin-content')?.innerText || '').length,
    theme: document.documentElement.dataset.theme || 'light',
    spinners: document.querySelectorAll('.admin-content .ant-spin-spinning, .admin-content .anticon-loading').length,
  }))
}

function visibleFnSource() {
  return `(el) => { if (!el) return false; const r = el.getBoundingClientRect(); const st = getComputedStyle(el); return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0' }`
}

async function waitReaction(page, before, reqBefore, dlBefore, timeout) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const ev = await page
      .evaluate(
        ({ before, reqBefore, dlBefore, dlNow, reqNow, reqTailNow }) => {
          const vis = (el) => {
            if (!el) return false
            const r = el.getBoundingClientRect()
            const st = getComputedStyle(el)
            return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0'
          }
          const modal = [...document.querySelectorAll('.ant-modal-wrap')].find(vis)
          if (modal) {
            const title = modal.querySelector('.ant-modal-title')?.innerText?.trim()
            return { kind: 'modal', text: `弹出对话框${title ? `「${title}」` : ''}` }
          }
          const drawer = [...document.querySelectorAll('.ant-drawer')].find(vis)
          if (drawer) return { kind: 'drawer', text: '抽屉面板出现' }
          const dropdown = [...document.querySelectorAll('.ant-dropdown, .ant-select-dropdown, .ant-picker-dropdown')].find(vis)
          if (dropdown) {
            const first = (dropdown.innerText || '').trim().split('\n')[0] || '菜单'
            return { kind: 'dropdown', text: `下拉/浮层面板出现（${first.slice(0, 24)}）` }
          }
          const pop = [...document.querySelectorAll('.ant-popover')].find(vis)
          if (pop) {
            const txt = (pop.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)
            return { kind: 'popover', text: `气泡确认出现（${txt}）` }
          }
          const note = [...document.querySelectorAll('.ant-notification-notice')].find(vis)
          if (note) return { kind: 'notification', text: `通知：${(note.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60)}` }
          const msg = [...document.querySelectorAll('.ant-message-notice')].find(vis)
          if (msg) return { kind: 'message', text: `提示消息：${(msg.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60)}` }
          if (dlNow > dlBefore) return { kind: 'download', text: '触发文件下载' }
          const theme = document.documentElement.dataset.theme || 'light'
          if (theme !== before.theme) return { kind: 'theme', text: `主题切换为 ${theme}` }
          if (location.hash && location.hash !== before.hash) return { kind: 'nav', text: `路由跳转到 ${location.hash}` }
          const rows = document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length
          if (rows !== before.rows) return { kind: 'rows', text: `表格行数 ${before.rows} → ${rows}` }
          const spinners = document.querySelectorAll('.admin-content .ant-spin-spinning, .admin-content .anticon-loading').length
          if (spinners > before.spinners) return { kind: 'loading', text: '出现加载状态（数据正在刷新）' }
          if (reqNow > reqBefore) return { kind: 'request', text: `向服务端发出请求（${reqTailNow || 'API'}）` }
          const txt = document.querySelector('.admin-content')?.innerText || ''
          if (window.__sweepHash(txt) !== before.textHash) {
            return { kind: 'text', text: `页面内容发生变化（${before.textLen} → ${txt.length} 字符）` }
          }
          return null
        },
        { before, reqBefore, dlBefore, dlNow: downloadSeq, reqNow: reqSeq, reqTailNow: reqTail },
      )
      .catch(() => null)
    if (ev) return ev
    await page.waitForTimeout(130)
  }
  return null
}

/** run a click, assert a visible reaction, print PASS/FAIL.
 *  prepare=false keeps already-open overlays (dialog/dropdown) alive. */
async function interact(page, pageLabel, actionName, clickFn, { timeout = 5000, prepare = true } = {}) {
  if (prepare) await closeOverlays(page)
  await page.mouse.move(3, 3).catch(() => {})
  await waitMessagesGone(page)
  await page.waitForTimeout(100)
  const before = await snapshot(page)
  const reqBefore = reqSeq
  const dlBefore = downloadSeq
  try {
    await clickFn()
  } catch (e) {
    const shot = await failureShot(page, pageLabel)
    fail(pageLabel, actionName, `点击失败：${shortErr(e)}`, shot)
    return { ok: false }
  }
  const ev = await waitReaction(page, before, reqBefore, dlBefore, timeout)
  if (!ev) {
    const shot = await failureShot(page, pageLabel)
    fail(pageLabel, actionName, `点击后 ${timeout}ms 内没有任何可见反应（无弹层/消息/请求/内容变化）`, shot)
    return { ok: false }
  }
  pass(pageLabel, actionName, ev.text)
  return { ok: true, evidence: ev }
}

/** Click a button inside an already-open dialog / confirm popup (overlays stay open). */
function clickDialog(page, pageLabel, actionName, re, opts = {}) {
  return interact(page, pageLabel, actionName, () => dialogButton(page, re).click({ timeout: 6000 }), {
    prepare: false,
    ...opts,
  })
}

// ---------------------------------------------------------------------------
// generic page sweep
// ---------------------------------------------------------------------------

const SKIP_RULES = [
  { re: /删除|移除|永久删除|重置密码|吊销|退出登录|注销/, why: '破坏性操作：只在本脚本自建对象上验证' },
  { re: /禁用/, why: '破坏性操作：只在本脚本自建对象上验证' },
]

async function sweepButtons(page, pageLabel, opts = {}) {
  const skipNames = opts.skipNames || []
  const skipReasons = opts.skipReasons || {}
  const maxSame = opts.maxSame || {}
  const defaultMaxSame = opts.defaultMaxSame ?? 2

  const items = await collectButtons(page, { includeOverlay: false })
  const nameCount = new Map()
  const planned = []
  for (const it of items) {
    const rule = SKIP_RULES.find((r) => r.re.test(it.name))
    if (it.switch) {
      skip(pageLabel, it.name || '开关', '开关类控件（启用/停用/授权）：只在本脚本自建对象上验证')
      continue
    }
    if (rule) {
      skip(pageLabel, it.name, rule.why)
      continue
    }
    if (skipNames.some((n) => norm(n) === norm(it.name))) {
      skip(pageLabel, it.name, skipReasons[it.name] || '按行操作：改在本脚本自建对象上验证，避免污染既有数据')
      continue
    }
    if (it.disabled) {
      skip(pageLabel, it.name, '按钮为禁用状态，不可点击')
      continue
    }
    if (it.loading) {
      skip(pageLabel, it.name, '按钮处于加载中状态')
      continue
    }
    const n = (nameCount.get(norm(it.name)) || 0) + 1
    nameCount.set(norm(it.name), n)
    const cap = maxSame[it.name] ?? defaultMaxSame
    if (n > cap) {
      skip(pageLabel, `${it.name}（第 ${n} 个）`, `同名按钮超过 ${cap} 个，同一动作已在首个按钮验证`)
      continue
    }
    planned.push(it)
  }

  if (!planned.length) return 0

  for (const it of planned) {
    const cur = await findButton(page, it.key, it.occurrence)
    if (!cur) {
      skip(pageLabel, it.name, '页面刷新后该按钮已不存在')
      continue
    }
    if (cur.disabled) {
      skip(pageLabel, it.name, '按钮变为禁用状态')
      continue
    }
    await interact(page, pageLabel, it.name, () => cur.handle.click({ timeout: 6000 }), {
      timeout: opts.timeout || 5000,
    })
    await closeOverlays(page)
    if (opts.returnTo) await ensurePage(page, pageLabel)
    await settle(page, 250)
  }
  return planned.length
}

// ---------------------------------------------------------------------------
// dedicated flows
// ---------------------------------------------------------------------------

async function waitMessage(page, re, timeout = 8000) {
  const deadline = Date.now() + timeout
  let seen = []
  while (Date.now() < deadline) {
    seen = await page.evaluate(() =>
      [...document.querySelectorAll('.ant-message-notice')].map((n) => (n.innerText || '').trim().replace(/\s+/g, ' ')),
    )
    const hit = seen.find((t) => re.test(t))
    if (hit) return hit
    await page.waitForTimeout(150)
  }
  return null
}

function rowBy(page, needle) {
  return page.locator('.ant-table-tbody tr.ant-table-row').filter({ hasText: needle })
}

async function modelsFlow(page, label) {
  const items = await collectButtons(page, { includeOverlay: false })
  const probes = items.filter((i) => norm(i.name) === '发起真实探测')
  if (!probes.length) {
    skip(label, '发起真实探测', '当前模型列表中没有真实探测按钮')
    return
  }
  const target = probes.find((p) => !p.disabled && !p.loading)
  if (!target) {
    observe(
      label,
      '发起真实探测',
      `真实探测按钮均被禁用（${probes.length} 个模型均未就绪或正在探测），未触发真实调用`,
    )
    return
  }
  await interact(page, label, `发起真实探测（真实模型调用，共 ${probes.length} 个按钮）`, () =>
    target.handle.click({ timeout: 6000 }),
  { timeout: 36000 })
  const msg = await waitMessage(page, /.+/, 35000)
  if (msg && /502|不可用|失败|没有返回验证响应/.test(msg)) {
    observe(
      label,
      '发起真实探测结果',
      `探测返回失败提示“${msg}”——外部模型中继 502，环境已知故障，非后台缺陷（HTTP 502 已记录为预期噪声）`,
    )
  } else if (msg) {
    observe(label, '发起真实探测结果', `探测提示：“${msg}”`)
  }
  await settle(page, 500)
}

async function usersFlow(page, label) {
  const email = `sweep-${RUN_ID}@example.com`
  const displayName = `Sweep${RUN_ID.slice(-6)}`
  const password = 'SweepPass123!'
  mine.userEmail = email
  mine.userName = displayName
  mine.userPassword = password

  // 1. create the throwaway user
  const openBtn = await findByName(page, '新建用户')
  if (!openBtn) {
    skip(label, '新建用户', '未找到新建用户按钮')
    return
  }
  const created = await interact(page, label, '新建用户（一次性账号）', () => openBtn.handle.click({ timeout: 6000 }))
  if (!created.ok) return
  await page.locator('.ant-modal input[placeholder="团队成员姓名"]').fill(displayName)
  await page.locator('.ant-modal input[placeholder="name@company.com"]').fill(email)
  await page.locator('.ant-modal input[placeholder="至少 10 个字符"]').first().fill(password)
  await clickDialog(page, label, `提交创建一次性账号 ${email}`, /创\s*建/)
  await waitMessage(page, /用户已创建/, 8000)
  const row = rowBy(page, email)
  const rowOk = await row.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  if (!rowOk) {
    const shot = await failureShot(page, label)
    fail(label, `创建一次性账号 ${email}`, '创建后表格中未出现该账号行', shot)
    return
  }
  pass(label, `一次性账号已创建并在列表可见`, `${displayName} / ${email}`)

  // 2. reset password on our own row
  await interact(page, label, `重置密码（自建账号 ${email}）`, () =>
    row.first().locator('button', { hasText: /重置密码/ }).first().click({ timeout: 6000 }),
  )
  await page.locator('.ant-modal input[placeholder="至少 10 个字符"]').first().fill('SweepPass456!').catch(() => {})
  await clickDialog(page, label, '提交重置密码（自建账号）', /重\s*置/)
  const resetMsg = await waitMessage(page, /密码已重置/, 8000)
  if (resetMsg) pass(label, '重置密码结果', resetMsg)
  else observe(label, '重置密码结果', '未捕获到“密码已重置”提示（可能已被后续操作覆盖）')

  // 3. revoke sessions on our own row
  await interact(page, label, `吊销会话（自建账号 ${email}）`, () =>
    row.first().locator('button', { hasText: /吊销会话/ }).first().click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认吊销会话（自建账号）', /吊销会话/)
  const revokeMsg = await waitMessage(page, /已吊销/, 8000)
  if (revokeMsg) pass(label, '吊销会话结果', revokeMsg)

  // 4. switch perms: is_active off -> on
  await interact(page, label, `停用账号开关（自建账号：关）`, () =>
    row.first().locator('button[role=switch]').nth(1).click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认停用账号（自建账号）', /确\s*认/)
  await waitMessage(page, /用户信息已更新/, 8000)
  await interact(page, label, `启用账号开关（自建账号：开）`, () =>
    row.first().locator('button[role=switch]').nth(1).click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认启用账号（自建账号）', /确\s*认/)
  await waitMessage(page, /用户信息已更新/, 8000)

  // 5. platform-admin switch on our own row, then back off
  await interact(page, label, `授予平台管理员（自建账号）`, () =>
    row.first().locator('button[role=switch]').nth(0).click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认授予平台管理员（自建账号）', /确\s*认/)
  await waitMessage(page, /用户信息已更新/, 8000)
  await interact(page, label, `移除平台管理员（自建账号）`, () =>
    row.first().locator('button[role=switch]').nth(0).click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认移除平台管理员（自建账号）', /确\s*认/)
  await waitMessage(page, /用户信息已更新/, 8000)

  // 6. cleanup: no data attached -> delete the throwaway account outright
  await interact(page, label, `清理：删除一次性账号 ${email}`, () =>
    row.first().locator('button').filter({ hasText: /删\s*除/ }).first().click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '清理：确认删除一次性账号', /删除账号|删\s*除/)
  await waitMessage(page, /账号已删除/, 8000)
  await page.waitForTimeout(1200)
  const gone = (await page.locator('.ant-table-row', { hasText: email }).count()) === 0
  if (gone) pass(label, '清理结果', `一次性账号 ${email} 已删除，列表里已消失`)
  else observe(label, '清理结果', `一次性账号 ${email} 删除后仍在列表中`)
}

async function workspacesFlow(page, label) {
  const name = `sweep-ws-${RUN_ID.slice(-6)}`
  mine.workspaceName = name

  const openBtn = await findByName(page, '新建工作区')
  if (!openBtn) {
    skip(label, '新建工作区', '未找到新建工作区按钮')
    return
  }
  const opened = await interact(page, label, '新建工作区（一次性工作区）', () => openBtn.handle.click({ timeout: 6000 }))
  if (!opened.ok) return
  await page.locator('.ant-modal input[placeholder="例如：产品研发中心"]').fill(name)
  await page.locator('.ant-modal .ant-select').first().click({ timeout: 6000 })
  await page.waitForSelector('.ant-select-dropdown:visible .ant-select-item-option', { timeout: 8000 }).catch(() => {})
  const option = page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: mine.userEmail }).first()
  const hasOption = await option.isVisible().catch(() => false)
  if (hasOption) {
    await option.click({ timeout: 6000 })
    pass(label, '选择工作区所有者', `下拉中选中一次性账号 ${mine.userEmail}`)
  } else {
    const fallback = page.locator('.ant-select-dropdown:visible .ant-select-item-option').first()
    await fallback.click({ timeout: 6000 }).catch(() => {})
    skip(label, '选择工作区所有者', `一次性账号未出现在下拉中，已回退选择第一个可用账号`)
  }
  await clickDialog(page, label, `提交创建一次性工作区 ${name}`, /创\s*建/)
  await waitMessage(page, /工作区已创建/, 8000)
  const row = rowBy(page, name)
  const ok = await row.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  if (!ok) {
    const shot = await failureShot(page, label)
    fail(label, `创建一次性工作区 ${name}`, '创建后列表未出现该工作区', shot)
    return
  }
  pass(label, '一次性工作区已创建', name)

  await interact(page, label, `删除一次性工作区（${name}）`, () =>
    row.first().locator('button', { hasText: /删\s*除/ }).first().click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认永久删除工作区（自建）', /永久删除/)
  const gone = await row.first().waitFor({ state: 'detached', timeout: 10000 }).then(() => true).catch(() => false)
  const msg = await waitMessage(page, /工作区已删除/, 6000)
  if (gone) pass(label, '清理结果', `一次性工作区“${name}”已永久删除并从列表消失${msg ? `（提示：${msg}）` : ''}`)
  else {
    const shot = await failureShot(page, label)
    fail(label, '清理结果', `一次性工作区“${name}”删除后仍在列表中`, shot)
  }
}

async function skillsFlow(page, label) {
  const base = `sweep_skill_${RUN_ID.slice(-6)}`
  mine.skills.push(base)

  const openBtn = await findByName(page, '新建技能')
  if (!openBtn) {
    skip(label, '新建技能', '未找到新建技能按钮')
    return
  }
  const opened = await interact(page, label, '新建技能（一次性技能）', () => openBtn.handle.click({ timeout: 6000 }))
  if (!opened.ok) return
  await page.locator('#skill-name').fill(base)
  await page.locator('#skill-description').fill('e2e sweep throwaway skill')
  await page.locator('#skill-system-prompt').fill('You are a throwaway skill created by the e2e sweep.')
  await clickDialog(page, label, `提交创建一次性技能 ${base}`, /确\s*认/)
  await waitMessage(page, /技能已创建/, 8000)
  const row = rowBy(page, base)
  const ok = await row.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  if (!ok) {
    const shot = await failureShot(page, label)
    fail(label, `创建一次性技能 ${base}`, '创建后列表未出现该技能', shot)
    return
  }
  pass(label, '一次性技能已创建', base)

  // edit our own skill
  await interact(page, label, `编辑（自建技能 ${base}）`, () =>
    row.first().locator('button', { hasText: /编\s*辑/ }).first().click({ timeout: 6000 }),
  )
  const modalTitle = await page.locator('.ant-modal-title').first().innerText().catch(() => '')
  if (/编辑技能/.test(modalTitle)) pass(label, '编辑弹窗内容', `弹窗标题“${modalTitle}”，名称字段已锁定`)
  await closeOverlays(page)

  // copy our own skill
  const beforeRows = await page.locator('.ant-table-tbody tr.ant-table-row').count()
  await interact(page, label, `复制（自建技能 ${base}）`, () =>
    row.first().locator('button', { hasText: /复\s*制/ }).first().click({ timeout: 6000 }),
  )
  const copyMsg = await waitMessage(page, /已复制为/, 8000)
  const copyName = copyMsg ? (copyMsg.match(/已复制为「(.+?)」/) || [])[1] || '' : ''
  if (copyName) {
    mine.skills.push(copyName)
    pass(label, '复制结果', `副本名称 ${copyName}`)
  }
  await page.waitForFunction((n) => document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length > n, beforeRows, { timeout: 8000 }).catch(() => {})

  // export our own skill (download)
  await interact(page, label, `导出（自建技能 ${base}）`, () =>
    row.first().locator('button', { hasText: /导\s*出/ }).first().click({ timeout: 6000 }),
  )
  await settle(page, 700)
  if (lastDownload) pass(label, '导出结果', `下载文件 ${lastDownload}`)

  // delete the copy, then the original (cleanup)
  const stillThere = new Set(mine.skills)
  for (const skillName of [...mine.skills].reverse()) {
    const target = rowBy(page, skillName)
    const exists = await target.first().isVisible().catch(() => false)
    if (!exists) {
      stillThere.delete(skillName)
      continue
    }
    await interact(page, label, `删除（自建技能 ${skillName}）`, () =>
      target.first().locator('button', { hasText: /删\s*除/ }).first().click({ timeout: 6000 }),
    )
    await clickDialog(page, label, `确认删除（自建技能 ${skillName}）`, /确\s*认/)
    const removed = await target.first().waitFor({ state: 'detached', timeout: 8000 }).then(() => true).catch(() => false)
    if (removed) {
      stillThere.delete(skillName)
      pass(label, '清理结果', `一次性技能 ${skillName} 已删除`)
    } else {
      observe(label, '清理结果', `一次性技能 ${skillName} 删除后仍在列表中，交由收尾兜底清理`)
    }
  }
  mine.skills = [...stillThere]
}

async function policiesFlow(page, label) {
  const role = `sweep_role_${RUN_ID.slice(-6)}`
  const resource = `sweep-resource-${RUN_ID.slice(-6)}`
  const draft = { role, resource, action: 'use' }
  const openBtn = await findByName(page, '添加策略')
  if (!openBtn) {
    skip(label, '添加策略', '未找到添加策略按钮')
    return
  }
  const opened = await interact(page, label, '添加策略（打开弹窗）', () => openBtn.handle.click({ timeout: 6000 }))
  if (!opened.ok) return
  await page.locator('#policy-role').fill(role)
  await page.locator('#policy-resource').fill(resource)
  await page.locator('#policy-action').fill('use')
  await clickDialog(page, label, `提交一次性策略 ${role}`, /确\s*认/)
  await waitMessage(page, /策略已添加/, 8000)
  const row = rowBy(page, resource)
  const ok = await row.first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false)
  if (!ok) {
    const shot = await failureShot(page, label)
    fail(label, `创建一次性策略 ${role}/${resource}`, '创建后列表未出现该策略', shot)
    return
  }
  pass(label, '一次性策略已创建', `${role} / ${resource} / use`)
  mine.policies.push(draft)

  await interact(page, label, `删除一次性策略 ${role}/${resource}`, () =>
    row.first().locator('button', { hasText: /删\s*除/ }).first().click({ timeout: 6000 }),
  )
  await clickDialog(page, label, '确认删除一次性策略', /确\s*认/)
  const removed = await row.first().waitFor({ state: 'detached', timeout: 8000 }).then(() => true).catch(() => false)
  if (removed) {
    mine.policies = mine.policies.filter((p) => p !== draft)
    pass(label, '清理结果', `一次性策略 ${role}/${resource} 已删除`)
  } else {
    const shot = await failureShot(page, label)
    fail(label, '清理结果', `一次性策略 ${role}/${resource} 删除后仍在列表中（交由收尾兜底清理）`, shot)
  }
}

async function usageControls(page, label) {
  const segs = await page.$$('.ant-segmented-item')
  for (const s of segs) {
    const text = norm(await s.innerText().catch(() => ''))
    if (!text) continue
    const cls = (await s.getAttribute('class')) || ''
    if (cls.includes('ant-segmented-item-selected')) {
      skip(label, `时间范围「${text}」`, '该项已选中，切换无变化')
      continue
    }
    const before = await snapshot(page)
    const reqBefore = reqSeq
    await s.click({ timeout: 5000 }).catch(() => {})
    const ev = await waitReaction(page, before, reqBefore, downloadSeq, 6000)
    if (ev) pass(label, `时间范围「${text}」`, ev.text)
    else {
      const shot = await failureShot(page, label)
      fail(label, `时间范围「${text}」`, '切换后没有可见反应', shot)
    }
  }
  const select = page.locator('.admin-content .ant-select').first()
  if (await select.isVisible().catch(() => false)) {
    const before = await snapshot(page)
    const reqBefore = reqSeq
    await select.click({ timeout: 5000 }).catch(() => {})
    const ev = await waitReaction(page, before, reqBefore, downloadSeq, 5000)
    if (ev) pass(label, '分组维度下拉框', ev.text)
    else fail(label, '分组维度下拉框', '点击后没有出现下拉面板')
    const opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '按账号' }).first()
    if (await opt.isVisible().catch(() => false)) {
      const b2 = await snapshot(page)
      const r2 = reqSeq
      await opt.click({ timeout: 5000 }).catch(() => {})
      const ev2 = await waitReaction(page, b2, r2, downloadSeq, 6000)
      if (ev2) pass(label, '切换分组维度为「按账号」', ev2.text)
      else fail(label, '切换分组维度为「按账号」', '切换后没有可见反应')
    } else {
      skip(label, '切换分组维度', '下拉选项未渲染“按账号”')
    }
    await closeOverlays(page)
  }
}

async function auditControls(page, label) {
  const picker = page.locator('.admin-content .ant-picker').first()
  if (await picker.isVisible().catch(() => false)) {
    const before = await snapshot(page)
    await picker.click({ timeout: 5000 }).catch(() => {})
    const ev = await waitReaction(page, before, reqSeq, downloadSeq, 4000)
    if (ev) pass(label, '日期范围选择器', ev.text === '出现加载状态（数据正在刷新）' ? '日期面板打开' : ev.text)
    else fail(label, '日期范围选择器', '点击后没有出现日期面板')
    const panel = await page.locator('.ant-picker-dropdown').first().isVisible().catch(() => false)
    if (!panel) fail(label, '日期面板可见性', '未检测到 .ant-picker-dropdown 面板')
    await closeOverlays(page)
  } else {
    skip(label, '日期范围选择器', '未找到日期选择器')
  }
}

async function dashboardControls(page, label) {
  // locators (not handles): the dashboard unmounts when a card navigates away
  const cards = page.locator('.stat-card')
  const total = await cards.count()
  for (let i = 0; i < total; i++) {
    const card = cards.nth(i)
    if (!(await card.isVisible().catch(() => false))) continue
    const text = (await card.innerText().catch(() => '')).replace(/\s+/g, ' ').trim().slice(0, 20)
    if (!text) continue
    const before = await snapshot(page)
    const reqBefore = reqSeq
    try {
      await card.click({ timeout: 5000 })
    } catch (e) {
      const shot = await failureShot(page, label)
      fail(label, `概览卡片「${text}」`, `点击失败：${shortErr(e)}`, shot)
      continue
    }
    const ev = await waitReaction(page, before, reqBefore, downloadSeq, 6000)
    if (ev) pass(label, `概览卡片「${text}」`, ev.text)
    else {
      const shot = await failureShot(page, label)
      fail(label, `概览卡片「${text}」`, '点击后没有可见反应', shot)
    }
    await ensurePage(page, label)
  }
}

async function headerFlow(page, context) {
  const label = '顶栏'
  visited.push(label)

  // theme toggle x2 (dark -> light)
  for (const round of [1, 2]) {
    const btn = await findByName(page, '切换深浅色主题', { chrome: true })
    if (!btn) {
      skip(label, '切换深浅色主题', '未找到主题切换按钮')
      break
    }
    await interact(page, label, `切换深浅色主题（第 ${round} 次）`, () => btn.handle.click({ timeout: 5000 }))
    await settle(page, 300)
  }

  // workspace switcher (open only, do not change the active workspace)
  const wsSelect = page.locator('.admin-workspace-switch .ant-select').first()
  if (await wsSelect.isVisible().catch(() => false)) {
    const before = await snapshot(page)
    await wsSelect.click({ timeout: 5000 }).catch(() => {})
    const ev = await waitReaction(page, before, reqSeq, downloadSeq, 4000)
    const opts = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').allInnerTexts().catch(() => [])
    if (ev && opts.length) pass(label, '切换当前工作区下拉', `下拉可见，选项：${opts.map((o) => o.trim()).join('、')}`)
    else if (ev) pass(label, '切换当前工作区下拉', ev.text)
    else fail(label, '切换当前工作区下拉', '点击后没有出现下拉面板')
    await closeOverlays(page)
  } else {
    skip(label, '切换当前工作区下拉', '未找到工作区切换控件')
  }

  // open user frontend in a new tab
  const openUser = (await findByName(page, '用户端', { chrome: true })) || (await findByName(page, '打开用户端', { chrome: true }))
  if (openUser) {
    const popupPromise = context.waitForEvent('page', { timeout: 8000 }).catch(() => null)
    const before = await snapshot(page)
    await openUser.handle.click({ timeout: 6000 }).catch(() => {})
    const popup = await popupPromise
    if (popup) {
      popups.push(popup.url())
      await popup.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {})
      popups.push(popup.url())
      pass(label, '用户端（新标签打开）', `新标签页地址 ${popup.url()}`)
      await popup.close().catch(() => {})
    } else {
      const ev = await waitReaction(page, before, reqSeq, downloadSeq, 3000)
      if (ev) pass(label, '用户端（新标签打开）', ev.text)
      else fail(label, '用户端（新标签打开）', '点击后没有打开新标签页，也没有可见反应')
    }
  } else {
    skip(label, '用户端（新标签打开）', '未找到用户端按钮')
  }

  // account dropdown: open + verify the logout entry is there, then close
  const accBtn = page.locator('.admin-header button.admin-account-button').first()
  if (await accBtn.isVisible().catch(() => false)) {
    const before = await snapshot(page)
    await accBtn.click({ timeout: 5000 }).catch(() => {})
    const ev = await waitReaction(page, before, reqSeq, downloadSeq, 4000)
    const items = await page.locator('.ant-dropdown:visible').first().innerText().catch(() => '')
    if (ev) pass(label, '账号菜单下拉', `下拉可见：${items.replace(/\s+/g, ' ').trim().slice(0, 40)}`)
    else fail(label, '账号菜单下拉', '点击后没有出现下拉菜单')
    await closeOverlays(page)
  } else {
    skip(label, '账号菜单下拉', '未找到账号菜单按钮')
  }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main() {
  const browser = await chromium.launch({
    channel: 'msedge',
    headless: true,
    ignoreDefaultArgs: ['--hide-scrollbars'],
  })
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
  context.setDefaultTimeout(20000)

  const page = await context.newPage()
  await page.addInitScript(() => {
    window.__sweepHash = (s) => {
      let h = 0
      const str = String(s || '')
      for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0
      return h
    }
  })

  page.on('request', (r) => {
    const url = r.url()
    if (/\/api\//.test(url)) {
      pendingApi++
      if (!url.includes('/api/v1/health')) {
        reqSeq++
        reqTail = `${r.method()} ${url.replace(/^https?:\/\/[^/]+/, '')}`
      }
    }
  })
  const settleRequest = (r) => {
    if (/\/api\//.test(r.url())) pendingApi = Math.max(0, pendingApi - 1)
  }
  page.on('requestfinished', settleRequest)
  page.on('requestfailed', settleRequest)
  page.on('pageerror', (e) => pageErrors.push({ page: currentPage, text: String((e && e.message) || e).slice(0, 300) }))
  page.on('console', (m) => {
    if (m.type() === 'error') {
      consoleErrors.push({ page: currentPage, text: m.text().slice(0, 300), url: m.location()?.url || '' })
    }
  })
  page.on('response', (r) => {
    if (r.status() >= 400 && !cleanupPhase) {
      const entry = {
        page: currentPage,
        status: r.status(),
        method: r.request().method(),
        url: r.url().replace(/^https?:\/\/[^/]+/, ''),
        screenshot: null,
      }
      httpErrors.push(entry)
      // grab visual evidence shortly after the UI shows the error message
      if (!expectedHttp(entry)) {
        setTimeout(() => {
          failureShot(page, currentPage)
            .then((rel) => {
              entry.screenshot = rel
            })
            .catch(() => {})
        }, 800)
      }
    }
  })
  page.on('download', (d) => {
    downloadSeq++
    lastDownload = d.suggestedFilename()
    downloads.push({ page: currentPage, file: lastDownload })
  })
  page.on('dialog', (d) => d.dismiss().catch(() => {}))

  try {
    // ---- login through the real form -------------------------------------
    currentPage = 'login'
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    const emailInput = page.locator('input[placeholder="name@company.com"]')
    await emailInput.waitFor({ timeout: 20000 })
    await emailInput.click()
    await emailInput.fill('')
    await emailInput.type(ADMIN_EMAIL, { delay: 12 })
    const pwdInput = page.locator('input[placeholder="请输入登录密码"]')
    await pwdInput.click()
    await pwdInput.type(ADMIN_PASSWORD, { delay: 12 })
    const submit = page.locator('button[type=submit]').first()
    const typedEmail = await emailInput.inputValue()
    const typedPwd = await pwdInput.inputValue()
    if (typedEmail !== ADMIN_EMAIL || typedPwd !== ADMIN_PASSWORD) {
      fail('登录', '表单输入', `输入框值不符合预期（email=${typedEmail}）`)
    }
    await submit.click({ timeout: 8000 })
    await page.waitForSelector('.admin-navigation .ant-menu-item', { timeout: 25000 })
    if (typedEmail === ADMIN_EMAIL && typedPwd === ADMIN_PASSWORD) {
      pass('登录', '表单登录', `真实输入框输入并提交成功，进入控制台（${ADMIN_EMAIL}）`)
    }
    await page.waitForTimeout(500)

    // ---- discover navigation --------------------------------------------
    const navLabels = await page.$$eval('.admin-navigation .ant-menu-item', (els) =>
      els.map((e) => e.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean),
    )
    log(`\n发现导航 ${navLabels.length} 项：${navLabels.join(' / ')}\n`)

    const perPageSkip = {
      '技能管理': {
        skipNames: ['编辑', '复制', '导出'],
        skipReasons: { 编辑: '按行操作：改在本脚本自建技能上验证', 复制: '按行操作：改在本脚本自建技能上验证', 导出: '按行操作：改在本脚本自建技能上验证' },
      },
      '模型中心': { skipNames: ['发起真实探测'], skipReasons: { 发起真实探测: '由模型探测专用流程触发（外部中继 502 属预期）' } },
      '用户管理': { skipNames: [], maxSame: { 刷新: 1 } },
      '工作区': { skipNames: [] },
    }

    for (let i = 0; i < navLabels.length; i++) {
      const label = navLabels[i]
      currentPage = label
      visited.push(label)
      log(`\n===== [${i + 1}/${navLabels.length}] ${label} =====`)
      const navigated = await clickNav(page, label)
      if (!navigated) {
        fail(label, '导航', '侧边栏中找不到该导航项')
        continue
      }
      await settlePage(page, label)
      const title = await pageTitle(page)
      if (norm(title) === norm(label)) pass(label, '页面加载', `页面标题「${title}」渲染完成`)
      else {
        const shot = await failureShot(page, label)
        fail(label, '页面加载', `页面标题为「${title || '(空)'}」，与导航项「${label}」不一致`, shot)
      }

      const n = String(i + 1).padStart(2, '0')
      const shotRel = `e2e/screens/admin-${n}-${slugOf(label)}.png`
      await page.screenshot({ path: path.join(SCREENS, `admin-${n}-${slugOf(label)}.png`) }).catch(() => {})

      const opts = perPageSkip[label] || {}
      const count = await sweepButtons(page, label, { ...opts, returnTo: true, timeout: 5000 })
      if (count === 0 && !(opts.skipNames || []).length) {
        skip(label, '(页面无按钮)', '该页面为只读展示页，没有可点击按钮')
      }

      // dedicated flows (throwaway objects / probes / controls)
      if (label === '用户管理') await usersFlow(page, label)
      else if (label === '工作区') await workspacesFlow(page, label)
      else if (label === '技能管理') await skillsFlow(page, label)
      else if (label === '权限策略') await policiesFlow(page, label)
      else if (label === '模型中心') await modelsFlow(page, label)
      else if (label === '用量统计') await usageControls(page, label)
      else if (label === '审计轨迹') await auditControls(page, label)
      else if (label === '平台概览') await dashboardControls(page, label)

      await closeOverlays(page)
      await settle(page, 200)
      log(`截图：${shotRel}`)
    }

    // ---- header chrome ---------------------------------------------------
    currentPage = '顶栏'
    log(`\n===== 顶栏控件 =====`)
    await ensurePage(page, navLabels[0] || '平台概览')
    await headerFlow(page, context)

    // ---- logout (final step) --------------------------------------------
    currentPage = '退出登录'
    log(`\n===== 退出登录（收尾） =====`)
    const accBtn = page.locator('.admin-header button.admin-account-button').first()
    if (await accBtn.isVisible().catch(() => false)) {
      await interact(page, '退出登录', '打开账号菜单', () => accBtn.click({ timeout: 5000 }))
      const logoutItem = page.locator('.ant-dropdown-menu-item').filter({ hasText: /退出登录/ }).first()
      await interact(page, '退出登录', '点击退出登录', () => logoutItem.click({ timeout: 5000 }), { prepare: false })
      const backToLogin = await page.waitForSelector('input[placeholder="name@company.com"]', { timeout: 10000 }).then(() => true).catch(() => false)
      if (backToLogin) pass('退出登录', '会话结束', '已退出并返回登录页')
      else {
        const shot = await failureShot(page, '退出登录')
        fail('退出登录', '会话结束', '退出后未返回登录页', shot)
      }
    } else {
      skip('退出登录', '退出登录', '未找到账号菜单按钮')
    }
  } catch (e) {
    fail(currentPage, '脚本异常', shortErr(e))
    await failureShot(page, currentPage)
  } finally {
    await cleanupAndReport(page).catch((e) => log(`报告生成异常：${shortErr(e)}`))
    await browser.close().catch(() => {})
  }
}

/** Safety net for leftover throwaway objects + final summary/report. */
async function cleanupAndReport(page) {
  cleanupPhase = true
  const leftovers = []
  const evalApi = (fn, arg) => page.evaluate(fn, arg).catch(() => null)
  const listing = await evalApi(async () => {
    const token = sessionStorage.getItem('futureagent.access_token')
    if (!token) return null
    const headers = { Authorization: `Bearer ${token}` }
    const [s, w, u] = await Promise.all([
      fetch('/api/v1/skills', { headers }),
      fetch('/api/v1/admin/workspaces', { headers }),
      fetch('/api/v1/admin/users?limit=200', { headers }),
    ])
    const out = { skills: [], workspaces: [], users: [] }
    if (s.ok) out.skills = ((await s.json()).skills || []).map((x) => x.name)
    if (w.ok) out.workspaces = ((await w.json()).workspaces || []).map((x) => ({ id: x.id, name: x.name }))
    if (u.ok) out.users = ((await u.json()).users || []).map((x) => ({ id: x.id, email: x.email, is_active: x.is_active }))
    return out
  })
  const api = (method, url, body) =>
    evalApi(
      async ({ method, url, body }) => {
        const token = sessionStorage.getItem('futureagent.access_token')
        if (!token) return -1
        const r = await fetch(url, {
          method,
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: body ? JSON.stringify(body) : undefined,
        })
        return r.status
      },
      { method, url, body },
    )

  if (listing) {
    for (const name of mine.skills) {
      if (!listing.skills.includes(name)) continue
      const s = await api('DELETE', `/api/v1/skills/${encodeURIComponent(name)}`)
      if (s === 204) leftovers.push(`技能 ${name}`)
    }
    for (const policy of mine.policies) {
      const s = await api('DELETE', '/api/v1/auth/policies', policy)
      if (s === 200 || s === 204) leftovers.push(`权限策略 ${policy.role}/${policy.resource}/${policy.action}`)
    }
    if (mine.workspaceName) {
      const ws = listing.workspaces.find((w) => w.name === mine.workspaceName)
      if (ws) {
        const s = await api('DELETE', `/api/v1/admin/workspaces/${ws.id}`)
        if (s === 200) leftovers.push(`工作区 ${mine.workspaceName}`)
      }
    }
    if (mine.userEmail) {
      const user = listing.users.find((u) => u.email === mine.userEmail)
      if (user) {
        // 一次性账号没有任何数据，直接删除；删不掉说明它的 guard 触发了，值得记一条。
        const s = await api('DELETE', `/api/v1/admin/users/${user.id}`)
        if (s !== 204) leftovers.push(`账号 ${mine.userEmail}（删除返回 ${s}，请人工确认）`)
      }
    }
  }
  if (leftovers.length) observe('清理兜底', 'API 兜底清理', `以下对象由兜底清理处理：${leftovers.join('；')}`)

  const obsProbe = httpErrors.filter((e) => /\/probe$/.test(e.url))
  if (obsProbe.length) {
    observe('模型中心', 'HTTP 观测', `模型探测接口返回 ${obsProbe.map((e) => e.status).join('/')}（${obsProbe.length} 次），外部中继 502 属环境已知故障`)
  }

  // ---- report ------------------------------------------------------------
  const unexpectedHttp = []
  for (const e of httpErrors) {
    const note = expectedHttp(e)
    if (note) {
      if (!observations.some((o) => o.action === 'HTTP 预期噪声' && o.detail.includes(String(e.status)))) {
        observe(e.page, 'HTTP 预期噪声', `${e.method} ${e.url} → ${e.status}（${note}）`)
      }
    } else {
      unexpectedHttp.push(e)
      fail(e.page, `[网络] ${e.method} ${e.url}`, `HTTP ${e.status}`, e.screenshot || null)
    }
  }

  const unexpectedConsole = []
  for (const c of consoleErrors) {
    const note = expectedConsole(c)
    if (note) observe(c.page, '控制台预期噪声', `${c.text.slice(0, 160)}（${note}）`)
    else unexpectedConsole.push(c)
  }
  for (const c of unexpectedConsole) {
    const owner = httpErrors.find((e) => e.screenshot && c.url && c.url.endsWith(e.url))
    fail(c.page, '[控制台] console.error', c.text.slice(0, 220), owner?.screenshot || null)
  }
  for (const p of pageErrors) {
    fail(p.page, '[页面异常] uncaught error', p.text)
  }

  log('\n================ SWEEP SUMMARY ================')
  log(`运行标识: ${RUN_ID}  时间: ${new Date().toISOString()}`)
  log(`访问页面 (${visited.length}): ${visited.join('、')}`)
  log(`PASS: ${stats.PASS}   FAIL: ${stats.FAIL}   SKIP: ${stats.SKIP}`)
  log(`导航截图: ${SCREENS}`)
  log(`失败截图目录: ${FAILURES}`)
  log(`下载文件: ${downloads.map((d) => `${d.file}(${d.page})`).join(', ') || '无'}`)
  log(`新标签页: ${[...new Set(popups)].join(', ') || '无'}`)
  if (failures.length) {
    log('\n--- 失败清单 ---')
    failures.forEach((f, i) => log(`${i + 1}. [${f.page}] ${f.action} — ${f.reason}${f.screenshot ? ` (截图 ${f.screenshot})` : ''}`))
  } else {
    log('\n无失败项。')
  }
  if (observations.length) {
    log('\n--- 观测项（非缺陷） ---')
    observations.forEach((o, i) => log(`${i + 1}. [${o.page}] ${o.action} — ${o.detail}`))
  }
  if (skips.length) {
    log(`\n--- 跳过项（${skips.length}） ---`)
    const grouped = new Map()
    for (const s of skips) {
      const k = `${s.page} :: ${s.reason}`
      grouped.set(k, (grouped.get(k) || 0) + 1)
    }
    for (const [k, v] of grouped) log(`${k} ×${v}`)
  }

  fs.writeFileSync(LOG_FILE, outLines.join('\n'), 'utf-8')
  fs.writeFileSync(
    JSON_FILE,
    JSON.stringify(
      {
        runId: RUN_ID,
        base: BASE,
        visited,
        stats,
        failures,
        observations,
        skips,
        httpErrors,
        consoleErrors,
        pageErrors,
        downloads,
        popups,
      },
      null,
      2,
    ),
    'utf-8',
  )
  log(`\n完整日志: ${LOG_FILE}`)
  log(`结构化结果: ${JSON_FILE}`)
}

main()
