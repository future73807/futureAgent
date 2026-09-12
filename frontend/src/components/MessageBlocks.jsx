// 助手消息的内联结构化卡片。
//
// "对话即工作台"要求消息自身携带足够的执行上下文：工具调用轨迹、真实
// token 用量、goal/loop 轮次判定、规划模式的计划、文件变更入口。原先这
// 些信息只留在工作模式页面或干脆不可见，用户必须跳出去才能了解 AI 做
// 了什么。这里按顺序渲染在助手气泡正文之后，缺数据时不渲染空壳。
import React, { useMemo, useState } from 'react'
import AntApp from 'antd/es/app'
import Button from 'antd/es/button'
import Collapse from 'antd/es/collapse'
import Drawer from 'antd/es/drawer'
import Flex from 'antd/es/flex'
import Modal from 'antd/es/modal'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Steps from 'antd/es/steps'
import Tag from 'antd/es/tag'
import Typography from 'antd/es/typography'
import { CheckCircleOutlined, CloseCircleOutlined, CopyOutlined, DiffOutlined, SaveOutlined } from '@ant-design/icons'
import WorkspaceChangesPanel from './WorkspaceChangesPanel.jsx'
import { apiFetch } from '../api.js'
import { parsePlanPayload } from '../plan-payload.js'
import { iterationVerdictLabel, skillDisplayName } from '../ui-labels.js'

const { Text } = Typography

// 这两类判定代表"非正常收尾"，用 warning 色与成功/进行中区分开。
const WARNING_VERDICTS = new Set(['budget_exhausted', 'judge_unavailable'])
// 会写盘的只读工具不在此列；make_* 覆盖所有生成类工具。
const WRITE_TOOLS = new Set(['write_file', 'edit_file'])

function isWriteTool(name) {
  const value = String(name || '')
  return WRITE_TOOLS.has(value) || value.startsWith('make_')
}

function truncate(text, max = 160) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > max ? `${value.slice(0, max)}…` : value
}

function formatTokens(value) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '0'
}

function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '操作未完成，请稍后重试。'
}

// 按顺序渲染助手消息的执行上下文；缺数据的块直接跳过。
export default function MessageBlocks({ message, canWrite = false }) {
  const { message: toast } = AntApp.useApp()
  const [changesOpen, setChangesOpen] = useState(false)
  const [saveOpen, setSaveOpen] = useState(false)
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [saveTaskId, setSaveTaskId] = useState('')
  const [saving, setSaving] = useState(false)

  const trace = Array.isArray(message?.tool_trace) ? message.tool_trace : []
  const usage = message?.usage && typeof message.usage === 'object' ? message.usage : null
  // run 总量已包含子代理，这里只列明细，避免与总量重复相加。
  const subagents = Array.isArray(usage?.subagents) ? usage.subagents : []
  const iterations = Array.isArray(message?.iterations) ? message.iterations : []
  const planPayload = useMemo(
    () => (message?.agent_mode === 'plan' ? parsePlanPayload(message?.content) : null),
    [message?.agent_mode, message?.content],
  )
  const hasChanges = trace.some((item) => isWriteTool(item?.name))

  // 工作模式的 run 记录没有 role 字段；有 role 时仍只承接助手消息。
  if (message?.role && message.role !== 'assistant') return null
  if (!trace.length && !usage && !iterations.length && !planPayload && !hasChanges) return null

  const openSaveDialog = async () => {
    setSaveOpen(true)
    if (tasks.length || tasksLoading) return
    setTasksLoading(true)
    try {
      const data = await apiFetch('/api/v1/tasks')
      setTasks(Array.isArray(data.tasks) ? data.tasks : [])
    } catch (error) {
      toast.error(readableError(error))
    } finally {
      setTasksLoading(false)
    }
  }

  const confirmSave = async () => {
    if (!saveTaskId) { toast.warning('请先选择要挂载计划的工作项'); return }
    setSaving(true)
    try {
      await apiFetch(`/api/v1/tasks/${saveTaskId}/plan`, {
        method: 'PUT',
        body: JSON.stringify({
          objective: planPayload.objective,
          steps: planPayload.steps.map((step) => ({ title: step.title, instructions: step.instructions })),
        }),
      })
      toast.success('已保存为工作计划')
      setSaveOpen(false)
    } catch (error) {
      toast.error(readableError(error))
    } finally {
      setSaving(false)
    }
  }

  const copyPlan = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(planPayload, null, 2))
      toast.success('已复制计划 JSON')
    } catch {
      toast.error('复制失败，请手动选择内容复制。')
    }
  }

  return (
    <div className="message-blocks">
      {trace.length > 0 && (
        <Collapse
          size="small"
          ghost
          className="message-card tool-trace-card"
          items={[{
            key: 'trace',
            label: <Text type="secondary">调用了 {trace.length} 个工具</Text>,
            children: (
              <div className="tool-trace-list">
                {trace.map((item, index) => (
                  <div key={item.tool_call_id || index} className="tool-trace-row">
                    <span className={item.status === 'success' ? 'tool-trace-ok' : 'tool-trace-fail'} aria-hidden>
                      {item.status === 'success' ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                    </span>
                    <Text strong className="tool-trace-name">{item.name}</Text>
                    {item.result_preview ? (
                      <Text type="secondary" className="tool-trace-preview">{truncate(item.result_preview)}</Text>
                    ) : null}
                  </div>
                ))}
              </div>
            ),
          }]}
        />
      )}

      {usage && (
        <div className="message-usage-chip">
          {formatTokens(usage.total_tokens)} token · 入 {formatTokens(usage.input_tokens)} / 出 {formatTokens(usage.output_tokens)} · 模型调用 {formatTokens(usage.llm_calls)} 次{usage.tool_calls ? ` · 工具调用 ${formatTokens(usage.tool_calls)} 次` : ''}
        </div>
      )}

      {subagents.length > 0 && (
        <Space size={[4, 4]} wrap className="message-subagents">
          {subagents.map((item, index) => (
            <Tag key={index} color="purple">子代理 · {skillDisplayName(item.skill_name)} · {item.model_id} · {formatTokens(item.total_tokens)} token</Tag>
          ))}
        </Space>
      )}

      {iterations.length > 0 && (
        <div className="message-card message-iteration-card">
          <Steps
            direction="vertical"
            size="small"
            className="message-iteration-steps"
            items={iterations.map((item) => ({
              title: `第 ${item.iteration} 轮 · ${iterationVerdictLabel(item.verdict)}`,
              description: item.reason || '',
              status: item.verdict === 'met' ? 'finish' : WARNING_VERDICTS.has(item.verdict) ? 'error' : 'process',
              className: WARNING_VERDICTS.has(item.verdict) ? 'iteration-warning' : undefined,
            }))}
          />
        </div>
      )}

      {planPayload && (
        <div className="message-card plan-card">
          <Flex justify="space-between" align="center" gap={8}>
            <Text strong>执行计划</Text>
            <Tag color="blue" style={{ marginInlineEnd: 0 }}>规划模式</Tag>
          </Flex>
          <div className="plan-card-objective">{planPayload.objective}</div>
          <ol className="plan-card-steps">
            {planPayload.steps.map((step, index) => (
              <li key={index}>
                <Text strong>{step.title}</Text>
                {step.instructions ? (
                  <div className="plan-card-instructions"><Text type="secondary">{step.instructions}</Text></div>
                ) : null}
              </li>
            ))}
          </ol>
          <Flex gap={8} wrap="wrap">
            {canWrite && (
              <Button size="small" type="primary" icon={<SaveOutlined />} onClick={openSaveDialog}>保存为工作计划</Button>
            )}
            <Button size="small" icon={<CopyOutlined />} onClick={copyPlan}>复制 JSON</Button>
          </Flex>
        </div>
      )}

      {hasChanges && (
        <Flex>
          <Button size="small" icon={<DiffOutlined />} onClick={() => setChangesOpen(true)}>查看文件变更</Button>
        </Flex>
      )}

      <Drawer
        title="工作区文件变更"
        width={780}
        open={changesOpen}
        onClose={() => setChangesOpen(false)}
        destroyOnHidden
      >
        <WorkspaceChangesPanel />
      </Drawer>

      <Modal
        title="保存为工作计划"
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={confirmSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Flex vertical gap={12}>
          <Text type="secondary">
            选择要挂载这份计划的工作项。保存后按工作区权限档位处理：默认档位需要人工批准，
            自动审批或完全访问档位会直接进入可执行状态。
          </Text>
          <Select
            showSearch
            placeholder={tasksLoading ? '正在加载工作项…' : '选择工作项'}
            loading={tasksLoading}
            value={saveTaskId || undefined}
            onChange={setSaveTaskId}
            optionFilterProp="label"
            options={tasks.map((item) => ({ value: item.id, label: item.title }))}
            notFoundContent={tasksLoading ? '加载中' : '暂无工作项，请先在看板中创建'}
          />
          {planPayload && (
            <div className="plan-card-preview">
              <Text strong>{planPayload.objective}</Text>
              <div><Text type="secondary">共 {planPayload.steps.length} 个步骤</Text></div>
            </div>
          )}
        </Flex>
      </Modal>
    </div>
  )
}
