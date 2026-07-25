import React, { lazy, Suspense, useEffect, useState } from 'react'
import zhCN from 'antd/es/locale/zh_CN'
import { App as AntApp, Avatar, Badge, Button, Card, ConfigProvider, Form, Input, Layout, Menu, Select, Space, Spin, Typography, theme } from 'antd'
import { ApiOutlined, AppstoreOutlined, AuditOutlined, DashboardOutlined, LogoutOutlined, RobotOutlined, SafetyOutlined, SettingOutlined, TeamOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import { apiFetch, applyAuthSession, clearAuthSession, getAccessToken, getWorkspaceId, refreshAccessToken, setWorkspaceId, serviceUrl, toUserErrorMessage } from './api.js'

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))
const ModelsPage = lazy(() => import('./pages/ModelsPage.jsx'))
const SkillsPage = lazy(() => import('./pages/SkillsPage.jsx'))
const McpPage = lazy(() => import('./pages/McpPage.jsx'))
const PoliciesPage = lazy(() => import('./pages/PoliciesPage.jsx'))
const SettingsPage = lazy(() => import('./pages/SettingsPage.jsx'))
const UsersPage = lazy(() => import('./pages/UsersPage.jsx'))
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage.jsx'))
const AuditPage = lazy(() => import('./pages/AuditPage.jsx'))

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography
const navItems = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: '平台概览' },
  { key: 'users', icon: <UserOutlined />, label: '用户管理' },
  { key: 'workspaces', icon: <TeamOutlined />, label: '工作区' },
  { key: 'audit', icon: <AuditOutlined />, label: '审计轨迹' },
  { type: 'divider' },
  { key: 'models', icon: <RobotOutlined />, label: '模型中心' },
  { key: 'skills', icon: <ToolOutlined />, label: '技能管理' },
  { key: 'mcp', icon: <ApiOutlined />, label: 'MCP 服务' },
  { key: 'policies', icon: <SafetyOutlined />, label: '权限策略' },
  { key: 'settings', icon: <SettingOutlined />, label: '运行设置' },
]

function Login({ onLogin }) {
  const { message } = AntApp.useApp(); const [loading, setLoading] = useState(false)
  const submit = async (values) => { setLoading(true); try { const data = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(values), workspaceId: '' }); applyAuthSession(data); onLogin(data) } catch (error) { message.error(toUserErrorMessage(error, '登录失败，请检查账号和网络后重试。')) } finally { setLoading(false) } }
  return <div className="admin-auth"><Card className="admin-auth-card"><Space direction="vertical" align="center" className="admin-auth-heading"><Avatar size={48} icon={<AppstoreOutlined />} /><Title level={2}>futureAgent 管理后台</Title><Text type="secondary">平台管理仅对已授权的运营人员开放。</Text></Space><Form layout="vertical" onFinish={submit} requiredMark={false} validateMessages={{ required: '${label}不能为空', types: { email: '${label}格式不正确' } }}><Form.Item name="email" label="管理员邮箱" rules={[{ required: true, type: 'email' }]}><Input autoComplete="email" autoFocus placeholder="请输入管理员邮箱" /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" placeholder="请输入密码" /></Form.Item><Button type="primary" htmlType="submit" size="large" block loading={loading}>登录管理后台</Button></Form></Card></div>
}

function AdminShell({ profile, workspaces, onLogout }) {
  const [selectedKey, setSelectedKey] = useState('dashboard'); const [collapsed, setCollapsed] = useState(false); const [online, setOnline] = useState(false); const [workspaceId, setCurrentWorkspace] = useState(getWorkspaceId() || workspaces[0]?.id || '')
  const userFrontendPort = window.location.port === '5174' ? 5173 : 8081
  useEffect(() => { setWorkspaceId(workspaceId) }, [workspaceId])
  useEffect(() => { const check = () => apiFetch('/api/v1/health', { workspaceId: '' }).then(() => setOnline(true)).catch(() => setOnline(false)); check(); const timer = setInterval(check, 30_000); return () => clearInterval(timer) }, [])
  const pages = { dashboard: <DashboardPage onNavigate={setSelectedKey} />, users: <UsersPage />, workspaces: <WorkspacesPage />, audit: <AuditPage />, models: <ModelsPage />, skills: <SkillsPage />, mcp: <McpPage />, policies: <PoliciesPage />, settings: <SettingsPage /> }
  return <Layout className="admin-layout"><Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={250} theme="dark" breakpoint="lg"><div className="admin-brand"><AppstoreOutlined />{!collapsed && <div><strong>futureAgent</strong><span>平台运营中心</span></div>}</div><Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={navItems} onClick={({ key }) => key && setSelectedKey(key)} /></Sider><Layout><Header className="admin-header"><Space><Text strong>{navItems.find((item) => item.key === selectedKey)?.label}</Text><Badge status={online ? 'success' : 'error'} text={online ? 'API 服务正常' : 'API 服务不可用'} /></Space><Space className="admin-header-actions"><Text type="secondary" className="workspace-label">当前工作区</Text><Select aria-label="切换当前工作区" size="small" value={workspaceId || undefined} onChange={setCurrentWorkspace} placeholder="选择工作区" notFoundContent="暂无可切换的工作区" style={{ width: 180 }} options={workspaces.map((item) => ({ value: item.id, label: item.name }))} /><Button href={serviceUrl(userFrontendPort)} target="_blank" rel="noreferrer">打开用户端</Button><Button type="text" icon={<LogoutOutlined />} onClick={onLogout} aria-label="退出登录" title="退出登录">{profile.display_name} · 退出登录</Button></Space></Header><Content className="admin-content"><Suspense fallback={<div className="admin-loading" aria-label="正在加载页面"><Spin size="large" tip="正在加载" /></div>}>{pages[selectedKey]}</Suspense></Content></Layout></Layout>
}

function AdminApp() {
  const { message } = AntApp.useApp(); const [session, setSession] = useState(null); const [restoring, setRestoring] = useState(true)
  useEffect(() => { const restore = async () => { try { if (!getAccessToken()) await refreshAccessToken(); const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) throw new Error('当前账号不是平台管理员') ; setSession(me) } catch { clearAuthSession() } finally { setRestoring(false) } }; restore() }, [])
  const loggedIn = async (payload) => { try { const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) { clearAuthSession(); throw new Error('当前账号不是平台管理员') } setSession(me) } catch (error) { message.error(toUserErrorMessage(error, '无法验证平台管理员权限，请重新登录后重试。')) } }
  const logout = async () => { try { await apiFetch('/api/v1/auth/logout', { method: 'POST', workspaceId: '' }) } catch { /* 清理本地凭据同样会结束当前会话。 */ } clearAuthSession(); setSession(null); message.success('已退出登录') }
  if (restoring) return <div className="admin-loading" aria-label="正在恢复登录状态"><Spin size="large" tip="正在恢复登录状态" /></div>
  return session ? <AdminShell profile={session.user} workspaces={session.workspaces || []} onLogout={logout} /> : <Login onLogin={loggedIn} />
}

export default function App() { return <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#4263eb', borderRadius: 14, colorBgLayout: '#f3f6fc', fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif' } }}><AntApp><AdminApp /></AntApp></ConfigProvider> }
