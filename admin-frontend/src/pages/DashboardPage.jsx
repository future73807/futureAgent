import React, { useEffect, useState } from 'react'
import { ApiOutlined, AuditOutlined, RobotOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Row, Space, Statistic, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography
const environmentLabels = { development: '本地开发', production: '生产环境', staging: '预发布环境', test: '测试环境' }

export default function DashboardPage({ onNavigate }) {
  const { message } = App.useApp(); const [data, setData] = useState({ counts: {} }); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setData(await apiFetch('/api/v1/admin/overview')) } catch (error) { message.error(toUserErrorMessage(error, '加载平台概览失败，请稍后重试。')) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const cards = [
    { title: '用户数', value: data.counts.users || 0, icon: <UserOutlined />, color: '#2563eb', bg: '#eff6ff', page: 'users' },
    { title: '工作区', value: data.counts.workspaces || 0, icon: <TeamOutlined />, color: '#7c3aed', bg: '#f5f3ff', page: 'workspaces' },
    { title: '任务数', value: data.counts.tasks || 0, icon: <AuditOutlined />, color: '#059669', bg: '#ecfdf5', page: 'audit' },
    { title: '模型路由', value: data.counts.models || 0, icon: <RobotOutlined />, color: '#d97706', bg: '#fffbeb', page: 'models' },
  ]
  return <div><div className="page-heading"><div><Title level={2}>平台概览</Title><Text type="secondary">运行环境：{environmentLabels[data.environment] || data.environment || '-'} · 默认模型：{data.default_model || '-'}</Text></div><Button loading={loading} onClick={load}>刷新</Button></div><Row gutter={[16, 16]}>{cards.map((item) => <Col xs={24} sm={12} xl={6} key={item.title}><Card className="admin-card stat-card" hoverable onClick={() => onNavigate(item.page)}><Space size={16}><span className="stat-icon" style={{ color: item.color, background: item.bg }}>{item.icon}</span><Statistic title={item.title} value={item.value} /></Space></Card></Col>)}</Row><Card className="admin-card" title="运营控制" style={{ marginTop: 20 }}><Space wrap><Button onClick={() => onNavigate('users')}>管理账号</Button><Button onClick={() => onNavigate('workspaces')}>查看租户边界</Button><Button onClick={() => onNavigate('audit')}>查看审计轨迹</Button><Button icon={<ApiOutlined />} onClick={() => onNavigate('mcp')}>探测 MCP 服务</Button></Space></Card></div>
}
