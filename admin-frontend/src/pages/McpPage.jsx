import React, { useEffect, useState } from 'react'
import { ApiOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Space, Table, Tag, Typography } from 'antd'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography

export default function McpPage() {
  const { message } = App.useApp()
  const [servers, setServers] = useState([])
  const [loading, setLoading] = useState(false)

  const load = async (probe = false) => {
    setLoading(true)
    try { setServers((await apiFetch(`/api/v1/mcp/servers?probe=${probe}`)).servers || []) }
    catch (error) { message.error(error.message) }
    finally { setLoading(false) }
  }
  useEffect(() => { load(false) }, [])

  const columns = [
    { title: '服务名', dataIndex: 'name', render: (value) => <span className="code-text">{value}</span> },
    { title: '地址', dataIndex: 'url', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'online' ? 'success' : value === 'offline' ? 'error' : 'processing'}>{value}</Tag> },
    { title: '工具', dataIndex: 'tools', render: (values) => <Space wrap>{(values || []).map((value) => <Tag color="cyan" key={value}>{value}</Tag>)}</Space> },
    { title: '错误', dataIndex: 'error', ellipsis: true, render: (value) => value ? <Text type="danger">{value}</Text> : '-' },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>MCP 服务</Title><Text type="secondary">检查服务连通性并发现可供 Agent 使用的工具</Text></div>
        <Button type="primary" icon={<ReloadOutlined />} onClick={() => load(true)} loading={loading}>检测连接</Button>
      </div>
      <Card className="admin-card"><Table rowKey="name" columns={columns} dataSource={servers} loading={loading} pagination={false} locale={{ emptyText: <Space><ApiOutlined />未配置 MCP 服务</Space> }} /></Card>
    </div>
  )
}
