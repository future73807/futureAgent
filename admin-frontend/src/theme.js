// 主题模式：写入 <html data-theme>，供 CSS 变量分层；持久化到 localStorage。
const KEY = 'futureagent.admin.theme'

export function getThemeMode() {
  try {
    const stored = localStorage.getItem(KEY)
    return stored === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function applyThemeMode(mode) {
  const next = mode === 'dark' ? 'dark' : 'light'
  try {
    localStorage.setItem(KEY, next)
  } catch { /* 隐私模式下仅会话内生效 */ }
  document.documentElement.dataset.theme = next
  window.dispatchEvent(new CustomEvent('futureagent-admin-theme', { detail: next }))
  return next
}

export function toggleThemeMode() {
  return applyThemeMode(getThemeMode() === 'dark' ? 'light' : 'dark')
}
