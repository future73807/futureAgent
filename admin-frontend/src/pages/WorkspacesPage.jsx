import React, { useEffect, useState } from 'react'
import { App, Button, Card, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography
export default function WorkspacesPage() {
  const { message } = App.useApp(); const [workspaces, setWorkspaces] = useState([]); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setWorkspaces((await apiFetch('/api/v1/admin/workspaces')).workspaces || []) } catch (error) { message.error(error.message) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const columns = [{ title: 'Workspace', render: (_, item) => <><Text strong>{item.name}</Text><br /><Text type="secondary" className="code-text">{item.slug}</Text></> }, { title: 'Plan', dataIndex: 'plan', render: (value) => <Tag color="blue">{value}</Tag> }, { title: 'Members', dataIndex: 'member_count' }, { title: 'Created', dataIndex: 'created_at', render: (value) => new Date(value).toLocaleString() }]
  return <div><div className="page-heading"><div><Title level={2}>Workspaces</Title><Text type="secondary">Tenant boundaries, ownership and membership are persisted independently of the browser.</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>Refresh</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={workspaces} loading={loading} /></Card></div>
}
