import React, { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Col, Row, Segmented, Select, Space, Statistic, Table, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography

const rangeOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天', value: '30d' },
  { label: '全部', value: 'all' },
]
const groupOptions = [
  { label: '按模型', value: 'model' },
  { label: '按账号', value: 'user' },
  { label: '按技能', value: 'skill' },
  { label: '按模式', value: 'mode' },
  { label: '按日期', value: 'day' },
]
const groupColumnTitle = { model: '模型', user: '账号', skill: '技能', mode: '运行模式', day: '日期' }
const modeLabels = { chat: '对话', plan: '规划', agent: '自主', goal: '目标', loop: '循环' }

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDuration(ms) {
  const total = Number(ms || 0)
  if (total < 1000) return `${total} 毫秒`
  if (total < 60_000) return `${(total / 1000).toFixed(1)} 秒`
  return `${(total / 60_000).toFixed(1)} 分钟`
}

// 未登记单价时不能显示 0，否则会被误读成“免费”；部分可定价时必须标注，
// 否则部分账单会被当成完整账单。
function costText(cost, pricedRows, runs) {
  if (cost === null || cost === undefined) return <Text type="secondary">未定价</Text>
  const value = Number(cost).toFixed(4)
  return pricedRows < runs ? <Text type="warning">{value}（部分可计价）</Text> : value
}

export default function UsagePage() {
  const { message } = App.useApp()
  const [data, setData] = useState({ totals: {}, groups: [] })
  const [range, setRange] = useState('30d')
  const [groupBy, setGroupBy] = useState('model')
  const [loading, setLoading] = useState(false)

  const load = async (next = {}) => {
    const usedRange = next.range ?? range
    const usedGroup = next.groupBy ?? groupBy
    setLoading(true)
    try {
      const params = new URLSearchParams({ range: usedRange, group_by: usedGroup })
      setData(await apiFetch(`/api/v1/admin/usage/summary?${params.toString()}`))
    } catch (error) {
      message.error(toUserErrorMessage(error, '加载用量统计失败，请稍后重试。'))
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const totals = data.totals || {}
  const groups = data.groups || []
  const partialPricing = (totals.priced_rows || 0) < (totals.runs || 0)
  const columns = [
    { title: groupColumnTitle[groupBy] || '维度', dataIndex: 'label', render: (value, row) => <span className="code-text">{groupBy === 'mode' ? (modeLabels[value || row.key] || value || row.key) : (value || row.key)}</span> },
    { title: '记录数', dataIndex: 'runs', width: 96 },
    { title: '模型调用', dataIndex: 'llm_calls', width: 104 },
    { title: '工具调用', dataIndex: 'tool_calls', width: 104 },
    { title: '输入 token', dataIndex: 'input_tokens', width: 124, align: 'right', render: formatNumber },
    { title: '输出 token', dataIndex: 'output_tokens', width: 124, align: 'right', render: formatNumber },
    { title: '总 token', dataIndex: 'total_tokens', width: 124, align: 'right', render: (value) => <Text strong>{formatNumber(value)}</Text> },
    { title: '累计耗时', dataIndex: 'duration_ms', width: 116, render: formatDuration },
    { title: '成本', width: 160, render: (_, row) => costText(row.cost, row.priced_rows, row.runs) },
  ]

  return <div>
    <div className="page-heading">
      <div>
        <Title level={2}>用量统计</Title>
        <Text type="secondary">跨工作区汇总模型真实上报的 token 与调用次数；成本仅在模型已登记单价时计算。</Text>
      </div>
      <Button icon={<ReloadOutlined />} loading={loading} onClick={() => load()}>刷新</Button>
    </div>

    <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
      <Col xs={12} md={6}><Card className="admin-card"><Statistic title="记录数" value={totals.runs || 0} /></Card></Col>
      <Col xs={12} md={6}><Card className="admin-card"><Statistic title="模型调用" value={totals.llm_calls || 0} /></Card></Col>
      <Col xs={12} md={6}><Card className="admin-card"><Statistic title="总 token" value={totals.total_tokens || 0} formatter={formatNumber} /></Card></Col>
      <Col xs={12} md={6}><Card className="admin-card"><Statistic title="工具调用" value={totals.tool_calls || 0} /></Card></Col>
    </Row>

    {data.truncated && <Alert style={{ marginBottom: 12 }} type="warning" showIcon message="结果已截断" description="匹配记录超过单次汇总上限，当前数字只反映最近的一部分，请缩小时间范围。" />}
    {partialPricing && (totals.runs || 0) > 0 && <Alert style={{ marginBottom: 12 }} type="info" showIcon message="部分模型未登记单价" description={`共 ${totals.runs} 条记录，其中 ${totals.priced_rows || 0} 条可计价。成本总额不是完整账单；请在 core/pricing.py 中按实际合约登记单价。`} />}

    <Card className="admin-card" styles={{ body: { paddingBottom: 10 } }}>
      <Space wrap style={{ marginBottom: 14 }}>
        <Segmented options={rangeOptions} value={range} onChange={(value) => { setRange(value); load({ range: value }) }} />
        <Select options={groupOptions} value={groupBy} onChange={(value) => { setGroupBy(value); load({ groupBy: value }) }} style={{ width: 130 }} />
      </Space>
      <Table rowKey="key" columns={columns} dataSource={groups} loading={loading} scroll={{ x: 1180 }} pagination={{ pageSize: 25 }} locale={{ emptyText: '所选范围内暂无用量记录' }} />
    </Card>
  </div>
}
