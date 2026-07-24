import React, { useEffect, useState } from 'react'
import { App, Button, Card, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography
export default function AuditPage() {
  const { message } = App.useApp(); const [events, setEvents] = useState([]); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setEvents((await apiFetch('/api/v1/admin/audit-events?limit=200')).events || []) } catch (error) { message.error(error.message) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const columns = [{ title: 'Time', dataIndex: 'created_at', width: 180, render: (value) => new Date(value).toLocaleString() }, { title: 'Action', dataIndex: 'action', render: (value) => <Tag color="blue">{value}</Tag> }, { title: 'Target', render: (_, event) => <span className="code-text">{event.target_type}:{event.target_id}</span> }, { title: 'Actor', dataIndex: 'actor_id', render: (value) => <span className="code-text">{value || 'system'}</span> }, { title: 'Metadata', dataIndex: 'metadata', render: (value) => <Text type="secondary" className="audit-meta">{JSON.stringify(value)}</Text> }]
  return <div><div className="page-heading"><div><Title level={2}>Audit trail</Title><Text type="secondary">Review security, workspace, task, plan, and agent activity recorded by the API.</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>Refresh</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={events} loading={loading} scroll={{ x: 1100 }} pagination={{ pageSize: 25 }} /></Card></div>
}
