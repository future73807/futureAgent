import { describe, expect, it } from 'vitest'
import { mcpDisplayName, mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from '../ui-labels.js'

describe('skillDisplayName', () => {
  it('maps default skill to Chinese label', () => {
    expect(skillDisplayName('default')).toBe('通用助手')
  })

  it('keeps custom skill names unchanged', () => {
    expect(skillDisplayName('coder')).toBe('coder')
  })
})

describe('mcpDisplayName', () => {
  it('maps known local tools server', () => {
    expect(mcpDisplayName('local_tools')).toBe('工作区与联网工具')
  })

  it('renders unknown servers with spaces instead of underscores', () => {
    expect(mcpDisplayName('custom_server')).toBe('custom server')
  })

  it('falls back to placeholder for empty values', () => {
    expect(mcpDisplayName('')).toBe('未命名工具服务')
  })
})

describe('mcpServerUnavailable', () => {
  it('marks offline/degraded/disabled servers unavailable', () => {
    for (const status of ['offline', 'degraded', 'disabled']) {
      expect(mcpServerUnavailable({ status })).toBe(true)
    }
  })

  it('keeps configured and online servers available', () => {
    expect(mcpServerUnavailable({ status: 'online' })).toBe(false)
    expect(mcpServerUnavailable({ status: 'configured' })).toBe(false)
  })
})

describe('mcpOptionLabel', () => {
  it('includes status and tool count for rich server objects', () => {
    const label = mcpOptionLabel({ name: 'local_tools', status: 'online', tools: ['list_files', 'read_file'] })
    expect(label).toContain('工作区与联网工具')
    expect(label).toContain('在线')
    expect(label).toContain('2 个工具')
  })
})
