// 规划模式输出的解析。
//
// 后端契约（core/agent_engine.py PLAN_OUTPUT_CONTRACT）要求模型"仅输出一段
// JSON"，但模型可能用 markdown 代码块包裹、或带少量前后缀说明。解析失败
// 必须返回 null：调用方原样展示正文，不能让模型输出被静默吞掉。
export function parsePlanPayload(content) {
  const text = String(content || '').trim()
  if (!text) return null
  const candidates = []
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (fenced) candidates.push(fenced[1])
  candidates.push(text)
  const first = text.indexOf('{')
  const last = text.lastIndexOf('}')
  if (first >= 0 && last > first) candidates.push(text.slice(first, last + 1))
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate)
      const objective = typeof parsed?.objective === 'string' ? parsed.objective.trim() : ''
      const steps = Array.isArray(parsed?.steps)
        ? parsed.steps
          .filter((item) => item && typeof item.title === 'string' && item.title.trim())
          .map((item) => ({
            title: item.title.trim(),
            instructions: typeof item.instructions === 'string' ? item.instructions.trim() : '',
          }))
        : []
      if (objective && steps.length) return { objective, steps }
    } catch { /* 尝试下一个候选。 */ }
  }
  return null
}
