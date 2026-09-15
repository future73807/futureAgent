import { describe, expect, it } from 'vitest'

import { formatRelativeTime, groupNotifications, notificationBucket, notificationKind, notificationTone } from '../notification-view.js'

describe('notificationTone', () => {
  it('把超时/失败类文案判为需要处理', () => {
    expect(notificationTone({ title: 'AI 执行需要处理：验收任务', body: 'AI 执行超过 180 秒限制，请检查模型路由后重试。' })).toBe('attention')
    expect(notificationTone({ title: '任务受阻', body: '' })).toBe('attention')
  })

  it('把完成类文案判为已完成', () => {
    expect(notificationTone({ title: 'AI 执行完成：验收任务', body: '结果已保存，等待人工审核' })).toBe('done')
    expect(notificationTone({ title: '计划已批准', body: '' })).toBe('done')
  })

  it('其它文案按信息类处理', () => {
    expect(notificationTone({ title: '新的评论', body: '看看这条' })).toBe('info')
    expect(notificationTone(null)).toBe('info')
  })
})

describe('notificationKind', () => {
  it('按 type 归类来源', () => {
    expect(notificationKind({ type: 'task' })).toBe('task')
    expect(notificationKind({ type: 'plan' })).toBe('plan')
    expect(notificationKind({ type: 'run' })).toBe('run')
    expect(notificationKind({ type: 'report_alert' })).toBe('alert')
    expect(notificationKind({})).toBe('default')
  })
})

describe('formatRelativeTime', () => {
  const now = new Date('2026-09-15T12:00:00').getTime()

  it('一分钟内显示刚刚', () => {
    expect(formatRelativeTime('2026-09-15T11:59:30', now)).toBe('刚刚')
  })

  it('按分钟、小时、天递进', () => {
    expect(formatRelativeTime('2026-09-15T11:35:00', now)).toBe('25 分钟前')
    expect(formatRelativeTime('2026-09-15T09:00:00', now)).toBe('3 小时前')
    expect(formatRelativeTime('2026-09-12T12:00:00', now)).toBe('3 天前')
  })

  it('超过一周回落到月日', () => {
    expect(formatRelativeTime('2026-08-20T12:00:00', now)).toBe('8 月 20 日')
  })

  it('空值与非法值返回空串', () => {
    expect(formatRelativeTime('', now)).toBe('')
    expect(formatRelativeTime('not-a-date', now)).toBe('')
  })
})

describe('groupNotifications', () => {
  const now = new Date('2026-09-15T12:00:00')

  it('按今天/昨天/更早分组且保持原顺序', () => {
    const groups = groupNotifications([
      { id: 'a', created_at: '2026-09-15T09:00:00' },
      { id: 'b', created_at: '2026-09-14T09:00:00' },
      { id: 'c', created_at: '2026-09-01T09:00:00' },
      { id: 'd', created_at: '2026-09-15T10:00:00' },
    ], now)
    expect(groups.map((group) => group.bucket)).toEqual(['今天', '昨天', '更早'])
    expect(groups[0].items.map((item) => item.id)).toEqual(['a', 'd'])
  })

  it('空分组不出现', () => {
    const groups = groupNotifications([{ id: 'a', created_at: '2026-09-15T09:00:00' }], now)
    expect(groups).toHaveLength(1)
    expect(groups[0].bucket).toBe('今天')
  })

  it('跨天的边界按本地日期算', () => {
    expect(notificationBucket('2026-09-15T00:05:00', now)).toBe('今天')
    expect(notificationBucket('2026-09-14T23:55:00', now)).toBe('昨天')
  })
})
