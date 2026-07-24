import React, { useEffect, useState } from 'react'
import { ApiOutlined, AuditOutlined, RobotOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Row, Space, Statistic, Typography } from 'antd'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography
export default function DashboardPage({ onNavigate }) {
  const { message } = App.useApp(); const [data, setData] = useState({ counts: {} }); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setData(await apiFetch('/api/v1/admin/overview')) } catch (error) { message.error(error.message) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const cards = [
    { title: 'Users', value: data.counts.users || 0, icon: <UserOutlined />, color: '#2563eb', bg: '#eff6ff', page: 'users' },
    { title: 'Workspaces', value: data.counts.workspaces || 0, icon: <TeamOutlined />, color: '#7c3aed', bg: '#f5f3ff', page: 'workspaces' },
    { title: 'Tasks', value: data.counts.tasks || 0, icon: <AuditOutlined />, color: '#059669', bg: '#ecfdf5', page: 'audit' },
    { title: 'Model routes', value: data.counts.models || 0, icon: <RobotOutlined />, color: '#d97706', bg: '#fffbeb', page: 'models' },
  ]
  return <div><div className="page-heading"><div><Title level={2}>Platform overview</Title><Text type="secondary">Environment: {data.environment || '-'} · Default model: {data.default_model || '-'}</Text></div><Button loading={loading} onClick={load}>Refresh</Button></div><Row gutter={[16, 16]}>{cards.map((item) => <Col xs={24} sm={12} xl={6} key={item.title}><Card className="admin-card stat-card" hoverable onClick={() => onNavigate(item.page)}><Space size={16}><span className="stat-icon" style={{ color: item.color, background: item.bg }}>{item.icon}</span><Statistic title={item.title} value={item.value} /></Space></Card></Col>)}</Row><Card className="admin-card" title="Operational controls" style={{ marginTop: 20 }}><Space wrap><Button onClick={() => onNavigate('users')}>Manage accounts</Button><Button onClick={() => onNavigate('workspaces')}>Review tenancy</Button><Button onClick={() => onNavigate('audit')}>Inspect audit trail</Button><Button icon={<ApiOutlined />} onClick={() => onNavigate('mcp')}>Probe MCP services</Button></Space></Card></div>
}
