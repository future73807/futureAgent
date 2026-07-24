import React, { useEffect, useState } from 'react'
import { App as AntApp, Avatar, Badge, Button, Card, ConfigProvider, Form, Input, Layout, Menu, Select, Space, Spin, Typography, theme } from 'antd'
import { ApiOutlined, AppstoreOutlined, AuditOutlined, DashboardOutlined, LinkOutlined, LogoutOutlined, RobotOutlined, SafetyOutlined, SettingOutlined, TeamOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import DashboardPage from './pages/DashboardPage.jsx'
import ModelsPage from './pages/ModelsPage.jsx'
import SkillsPage from './pages/SkillsPage.jsx'
import McpPage from './pages/McpPage.jsx'
import PoliciesPage from './pages/PoliciesPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import UsersPage from './pages/UsersPage.jsx'
import WorkspacesPage from './pages/WorkspacesPage.jsx'
import AuditPage from './pages/AuditPage.jsx'
import { apiFetch, applyAuthSession, clearAuthSession, getAccessToken, getWorkspaceId, refreshAccessToken, setWorkspaceId, serviceUrl } from './api.js'

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography
const navItems = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: 'Overview' },
  { key: 'users', icon: <UserOutlined />, label: 'Users' },
  { key: 'workspaces', icon: <TeamOutlined />, label: 'Workspaces' },
  { key: 'audit', icon: <AuditOutlined />, label: 'Audit trail' },
  { type: 'divider' },
  { key: 'models', icon: <RobotOutlined />, label: 'Models & routing' },
  { key: 'skills', icon: <ToolOutlined />, label: 'Skills' },
  { key: 'mcp', icon: <ApiOutlined />, label: 'MCP services' },
  { key: 'policies', icon: <SafetyOutlined />, label: 'Policies' },
  { key: 'settings', icon: <SettingOutlined />, label: 'Runtime settings' },
]

function Login({ onLogin }) {
  const { message } = AntApp.useApp(); const [loading, setLoading] = useState(false)
  const submit = async (values) => { setLoading(true); try { const data = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(values), workspaceId: '' }); applyAuthSession(data); onLogin(data) } catch (error) { message.error(error.message) } finally { setLoading(false) } }
  return <div className="admin-auth"><Card className="admin-auth-card"><Space direction="vertical" align="center" className="admin-auth-heading"><Avatar size={48} icon={<AppstoreOutlined />} /><Title level={2}>futureAgent Admin</Title><Text type="secondary">Platform administration is restricted to authorized operators.</Text></Space><Form layout="vertical" onFinish={submit} requiredMark={false}><Form.Item name="email" label="Administrator email" rules={[{ required: true, type: 'email' }]}><Input autoComplete="email" /></Form.Item><Form.Item name="password" label="Password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item><Button type="primary" htmlType="submit" size="large" block loading={loading}>Sign in to admin</Button></Form></Card></div>
}

function AdminShell({ profile, workspaces, onLogout }) {
  const [selectedKey, setSelectedKey] = useState('dashboard'); const [collapsed, setCollapsed] = useState(false); const [online, setOnline] = useState(false); const [workspaceId, setCurrentWorkspace] = useState(getWorkspaceId() || workspaces[0]?.id || '')
  useEffect(() => { setWorkspaceId(workspaceId) }, [workspaceId])
  useEffect(() => { const check = () => apiFetch('/api/v1/health', { workspaceId: '' }).then(() => setOnline(true)).catch(() => setOnline(false)); check(); const timer = setInterval(check, 30_000); return () => clearInterval(timer) }, [])
  const pages = { dashboard: <DashboardPage onNavigate={setSelectedKey} />, users: <UsersPage />, workspaces: <WorkspacesPage />, audit: <AuditPage />, models: <ModelsPage />, skills: <SkillsPage />, mcp: <McpPage />, policies: <PoliciesPage />, settings: <SettingsPage /> }
  return <Layout className="admin-layout"><Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={240} theme="dark" breakpoint="lg"><div className="admin-brand"><AppstoreOutlined />{!collapsed && <div><strong>futureAgent</strong><span>Platform administration</span></div>}</div><Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={navItems} onClick={({ key }) => key && setSelectedKey(key)} /></Sider><Layout><Header className="admin-header"><Space><Text strong>{navItems.find((item) => item.key === selectedKey)?.label}</Text><Badge status={online ? 'success' : 'error'} text={online ? 'API online' : 'API unavailable'} /></Space><Space><Select size="small" value={workspaceId || undefined} onChange={setCurrentWorkspace} style={{ width: 180 }} options={workspaces.map((item) => ({ value: item.id, label: item.name }))} /><Button icon={<LinkOutlined />} href={serviceUrl(5173)} target="_blank">User workspace</Button><Button type="primary" icon={<RobotOutlined />} href={serviceUrl(4000, '/ui')} target="_blank">LiteLLM</Button><Button type="text" icon={<LogoutOutlined />} onClick={onLogout}>{profile.display_name}</Button></Space></Header><Content className="admin-content">{pages[selectedKey]}</Content></Layout></Layout>
}

function AdminApp() {
  const { message } = AntApp.useApp(); const [session, setSession] = useState(null); const [restoring, setRestoring] = useState(true)
  useEffect(() => { const restore = async () => { try { if (!getAccessToken()) await refreshAccessToken(); const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) throw new Error('This account is not a platform administrator'); setSession(me) } catch { clearAuthSession() } finally { setRestoring(false) } }; restore() }, [])
  const loggedIn = async (payload) => { try { const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) { clearAuthSession(); throw new Error('This account is not a platform administrator') } setSession(me) } catch (error) { message.error(error.message) } }
  const logout = async () => { try { await apiFetch('/api/v1/auth/logout', { method: 'POST', workspaceId: '' }) } catch { /* Clearing local credentials is sufficient. */ } clearAuthSession(); setSession(null); message.success('Signed out') }
  if (restoring) return <div className="admin-loading"><Spin size="large" /></div>
  return session ? <AdminShell profile={session.user} workspaces={session.workspaces || []} onLogout={logout} /> : <Login onLogin={loggedIn} />
}

export default function App() { return <ConfigProvider theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#2563eb', borderRadius: 8, colorBgLayout: '#f3f4f6' } }}><AntApp><AdminApp /></AntApp></ConfigProvider> }
