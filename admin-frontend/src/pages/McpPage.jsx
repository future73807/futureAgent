import React, { useEffect, useState } from 'react'
import { ApiOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Space, Table, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography
const statusLabels = { configured: '已配置', online: '在线', offline: '离线', unknown: '未知', degraded: '异常', disabled: '已禁用' }

export default function McpPage() {
  const { message } = App.useApp()
  const [servers, setServers] = useState([])
  const [loading, setLoading] = useState(false)

  const load = async (probe = false) => {
    setLoading(true)
    try { setServers((await apiFetch(`/api/v1/mcp/servers?probe=${probe}`)).servers || []) }
    catch (error) { message.error(toUserErrorMessage(error, '加载 MCP 服务状态失败，请稍后重试。')) }
    finally { setLoading(false) }
  }
  useEffect(() => { load(false) }, [])

  const columns = [
    { title: '服务名', dataIndex: 'name', width: 140, render: (value) => <span className="code-text">{value}</span> },
    { title: '地址', dataIndex: 'url', ellipsis: true, responsive: ['md'] },
    { title: '状态', dataIndex: 'status', width: 96, render: (value) => <Tag color={value === 'online' ? 'success' : value === 'offline' ? 'error' : value === 'configured' ? 'blue' : 'processing'}>{statusLabels[value] || '未知'}</Tag> },
    { title: '工具', dataIndex: 'tools', responsive: ['sm'], render: (values, record) => values?.length ? <Space wrap>{values.map((value) => <Tag color="cyan" key={value}>{value}</Tag>)}</Space> : <Text type="secondary">{record.status === 'configured' ? '检测后显示' : '暂无'}</Text> },
    { title: '错误', dataIndex: 'error', ellipsis: true, responsive: ['lg'], render: (value) => value ? <Text type="danger">{toUserErrorMessage(value, 'MCP 服务探测失败，请检查服务配置和连接状态。')}</Text> : '-' },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>MCP 服务</Title><Text type="secondary">检查服务连通性并发现可供智能助手使用的工具</Text></div>
        <Button type="primary" icon={<ReloadOutlined />} onClick={() => load(true)} loading={loading}>检测连接</Button>
      </div>
      <Card className="admin-card"><Table rowKey="name" columns={columns} dataSource={servers} loading={loading} pagination={false} locale={{ emptyText: <Space><ApiOutlined />未配置 MCP 服务</Space> }} /></Card>
    </div>
  )
}
