import { describe, expect, it } from 'vitest'
import { parsePlanPayload } from '../plan-payload.js'

describe('parsePlanPayload', () => {
  it('parses the bare JSON contract from the backend', () => {
    const payload = parsePlanPayload('{"objective": "完成发布", "steps": [{"title": "起草说明", "instructions": "写出三章"}]}')
    expect(payload).toEqual({ objective: '完成发布', steps: [{ title: '起草说明', instructions: '写出三章' }] })
  })

  it('unwraps markdown fenced code blocks', () => {
    const content = '```json\n{"objective": "整理数据", "steps": [{"title": "清洗", "instructions": ""}]}\n```'
    expect(parsePlanPayload(content)?.objective).toBe('整理数据')
  })

  it('extracts the JSON object when surrounded by prose', () => {
    const content = '已核实事实如下：\n{"objective": "上线功能", "steps": [{"title": "回归", "instructions": ""}]}\n请确认。'
    expect(parsePlanPayload(content)?.steps[0].title).toBe('回归')
  })

  it('returns null for malformed JSON so the caller keeps the raw text', () => {
    expect(parsePlanPayload('{"objective": "坏 JSON", steps: [')).toBeNull()
  })

  it('returns null when steps are missing or empty', () => {
    expect(parsePlanPayload('{"objective": "只有目标"}')).toBeNull()
    expect(parsePlanPayload('{"objective": "只有目标", "steps": []}')).toBeNull()
  })

  it('drops steps without a usable title and trims values', () => {
    const payload = parsePlanPayload('{"objective": " 修剪  ", "steps": [{"title": "  步骤一  ", "instructions": "  说明  "}, {"instructions": "无标题"}]}')
    expect(payload).toEqual({ objective: '修剪', steps: [{ title: '步骤一', instructions: '说明' }] })
  })

  it('returns null for empty input', () => {
    expect(parsePlanPayload('')).toBeNull()
    expect(parsePlanPayload(null)).toBeNull()
  })
})
