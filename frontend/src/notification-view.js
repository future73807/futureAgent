// 通知中心的展示逻辑（纯函数，便于单测）。
//
// 通知表只存 type/title/body/read/created_at：语义强度（"完成"还是"需要处理"）
// 只在文案里，所以强弱判定放在这里做一次，界面各处不再各写一套正则。

/** 需要用户立刻处理的通知：失败、超时、风险、预警。 */
const ATTENTION_PATTERN = /需要处理|失败|超时|异常|风险|预警|受阻|错误/
/** 正常收尾的通知：完成、批准、成功。 */
const DONE_PATTERN = /完成|已批准|成功|通过/

/**
 * 通知的语义强度：attention（要处理）/ done（已完成）/ info（其它）。
 * 只看文案不看 type——同是 run 类型，成功与超时得区分开。
 */
export function notificationTone(item) {
  const text = `${item?.title || ''} ${item?.body || ''}`
  if (ATTENTION_PATTERN.test(text)) return 'attention'
  if (DONE_PATTERN.test(text)) return 'done'
  return 'info'
}

/** 通知来源图标名（由调用方映射到具体图标组件）。 */
export function notificationKind(item) {
  const type = String(item?.type || '')
  if (type === 'task') return 'task'
  if (type === 'plan') return 'plan'
  if (type === 'run') return 'run'
  if (/预警|alert/i.test(type)) return 'alert'
  return 'default'
}

/**
 * 相对时间：刚刚 / N 分钟前 / N 小时前 / N 天前 / 月 日。
 * 精确时间挂在 title 上，需要时仍可核对。
 */
export function formatRelativeTime(value, now = Date.now()) {
  if (!value) return ''
  const then = new Date(value)
  const time = then.getTime()
  if (Number.isNaN(time)) return ''
  const diff = Math.max(0, now - time)
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return `${then.getMonth() + 1} 月 ${then.getDate()} 日`
}

/** 分组标签：今天 / 昨天 / 更早。 */
export function notificationBucket(value, now = new Date()) {
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return '更早'
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const time = then.getTime()
  if (time >= startOfToday) return '今天'
  if (time >= startOfToday - 24 * 60 * 60 * 1000) return '昨天'
  return '更早'
}

/**
 * 按天分组，保持传入顺序（列表本身已按时间倒序）。
 * 返回 [{ bucket, items }]，空分组不出现。
 */
export function groupNotifications(items, now = new Date()) {
  const order = ['今天', '昨天', '更早']
  const buckets = new Map(order.map((bucket) => [bucket, []]))
  ;(items || []).forEach((item) => {
    buckets.get(notificationBucket(item?.created_at, now)).push(item)
  })
  return order
    .map((bucket) => ({ bucket, items: buckets.get(bucket) }))
    .filter((group) => group.items.length)
}
