/** 登录页全屏效果 + 退出后回登录页的截图。 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:5173'
const OUT = process.env.SCREEN_DIR || 'e2e/screens'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || 'msedge', headless: true, ignoreDefaultArgs: ['--hide-scrollbars'] })
for (const [width, height, tag] of [[1440, 900, 'desktop'], [1180, 720, 'laptop'], [820, 900, 'narrow']]) {
  const context = await browser.newContext({ viewport: { width, height }, locale: 'zh-CN' })
  const page = await context.newPage()
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.auth-card', { timeout: 15000 })
  await page.waitForTimeout(600)
  const box = await page.locator('.auth-page').boundingBox()
  console.log(`${tag} ${width}x${height}: .auth-page = ${Math.round(box.width)}x${Math.round(box.height)}`)
  if (Math.round(box.width) !== width || Math.round(box.height) < height) {
    console.log(`  ❌ 没有铺满视口`)
  } else {
    console.log('  ✅ 铺满视口')
  }
  await page.screenshot({ path: `${OUT}/00-login-${tag}.png` })
  await context.close()
}
await browser.close()
console.log('login screenshots written')
