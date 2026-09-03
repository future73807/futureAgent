import { describe, expect, it } from 'vitest'
import { formatDateTime } from '../formatters.js'

describe('formatDateTime', () => {
  it('returns em dash for empty values', () => {
    expect(formatDateTime('')).toBe('—')
    expect(formatDateTime(null)).toBe('—')
  })

  it('returns em dash for unparseable values', () => {
    expect(formatDateTime('not-a-date')).toBe('—')
  })

  it('formats valid dates in zh-CN', () => {
    const text = formatDateTime('2026-09-02T01:35:50Z')
    expect(text).toContain('2026')
    expect(text).not.toBe('—')
  })
})
